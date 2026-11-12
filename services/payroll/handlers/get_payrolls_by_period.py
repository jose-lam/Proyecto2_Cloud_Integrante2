import math
import os
import re
from shared.middlewares.db_tenant_middleware import with_tenant_db
from shared.utils.response import success, error
from shared.utils.s3_helper import generate_download_presigned_url

S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME", "[FALTA_INTEGRANTE_1_NOMBRE_BUCKET_S3]")
PERIOD_REGEX = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
ALLOWED_PAYROLL_ROLES = {"ADMIN", "HR_ADMIN", "HR", "PAYROLL_ADMIN", "MANAGER"}


@with_tenant_db
def lambda_handler(event, context, conn, cursor, tenant_id, role, auth_employee_id):
    """
    GET /payrolls/{period}?page=1&limit=20
    Retorna el resumen consolidado del periodo y las boletas paginadas del tenant.
    """
    if role not in ALLOWED_PAYROLL_ROLES:
        return error(403, "No tiene permisos para consultar el consolidado de nómina")

    path_params = event.get("pathParameters") or {}
    period = str(path_params.get("period", "")).strip()

    if not PERIOD_REGEX.match(period):
        return error(400, "El parámetro 'period' debe tener formato YYYY-MM (ej. 2026-11)")

    query_params = event.get("queryStringParameters") or {}
    try:
        page = max(1, int(query_params.get("page", 1)))
        limit = min(100, max(1, int(query_params.get("limit", 20))))
    except ValueError:
        return error(400, "Los parámetros 'page' y 'limit' deben ser enteros positivos")

    offset = (page - 1) * limit

    # 1. Consultar cabecera del periodo
    cursor.execute(
        """
        SELECT period_id, period_name, is_closed, total_paid, created_at
        FROM payroll_periods
        WHERE period_name = %s;
        """,
        (period,)
    )
    period_row = cursor.fetchone()

    if not period_row:
        return error(404, f"No se encontró información de nómina para el periodo {period}")

    period_id = str(period_row["period_id"])

    # 2. Consultar métricas agregadas y conteo total de boletas
    cursor.execute(
        """
        SELECT
            COUNT(*) AS total_slips,
            COALESCE(SUM(base_salary), 0.00) AS total_base_salary,
            COALESCE(SUM(deductions), 0.00) AS total_deductions,
            COALESCE(SUM(net_pay), 0.00) AS total_net_pay
        FROM pay_slips
        WHERE period_id = %s;
        """,
        (period_id,)
    )
    agg = cursor.fetchone()
    total_items = int(agg["total_slips"])
    total_pages = math.ceil(total_items / limit) if total_items > 0 else 1

    # 3. Consultar boletas paginadas enriquecidas con datos del empleado
    cursor.execute(
        """
        SELECT
            ps.pay_slip_id,
            ps.period_id,
            ps.employee_id,
            COALESCE(e.first_name || ' ' || e.last_name, esp.email, 'Empleado') AS employee_name,
            COALESCE(e.email, esp.email) AS email,
            ps.base_salary,
            ps.deductions,
            ps.net_pay,
            ps.s3_slip_key,
            ps.generated_at
        FROM pay_slips ps
        LEFT JOIN employees e ON ps.employee_id = e.employee_id
        LEFT JOIN employee_salary_profiles esp ON ps.employee_id = esp.employee_id
        WHERE ps.period_id = %s
        ORDER BY ps.generated_at DESC, ps.employee_id ASC
        LIMIT %s OFFSET %s;
        """,
        (period_id, limit, offset)
    )
    rows = cursor.fetchall()

    items = []
    for row in rows:
        s3_key = row.get("s3_slip_key")
        download_url = None
        if s3_key and s3_key.startswith(f"{tenant_id}/payroll/slips/"):
            download_url = generate_download_presigned_url(
                bucket_name=S3_BUCKET_NAME,
                key=s3_key,
                expires_in=900
            )

        items.append({
            "paySlipId": str(row["pay_slip_id"]),
            "employeeId": str(row["employee_id"]),
            "employeeName": row["employee_name"],
            "email": row["email"],
            "baseSalary": float(row["base_salary"]),
            "deductions": float(row["deductions"]),
            "netPay": float(row["net_pay"]),
            "s3SlipKey": s3_key,
            "downloadUrl": download_url,
            "generatedAt": row["generated_at"].isoformat() if row["generated_at"] else None
        })

    return success(200, {
        "period": {
            "periodId": period_id,
            "periodName": period_row["period_name"],
            "isClosed": period_row["is_closed"],
            "totalPaid": float(period_row["total_paid"]),
            "createdAt": period_row["created_at"].isoformat() if period_row["created_at"] else None
        },
        "summary": {
            "employeesCount": total_items,
            "totalBaseSalary": float(agg["total_base_salary"]),
            "totalDeductions": float(agg["total_deductions"]),
            "totalNetPay": float(agg["total_net_pay"])
        },
        "items": items,
        "pagination": {
            "page": page,
            "limit": limit,
            "totalItems": total_items,
            "totalPages": total_pages
        }
    })
