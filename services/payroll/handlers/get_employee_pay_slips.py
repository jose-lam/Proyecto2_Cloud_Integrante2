import math
import os
import uuid
from shared.middlewares.db_tenant_middleware import with_tenant_db
from shared.utils.response import success, error
from shared.utils.s3_helper import generate_download_presigned_url

S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME", "[FALTA_INTEGRANTE_1_NOMBRE_BUCKET_S3]")


@with_tenant_db
def lambda_handler(event, context, conn, cursor, tenant_id, role, auth_employee_id):
    """
    GET /payrolls/employee/{employee_id}?page=1&limit=12
    Retorna el historial de boletas del empleado con sus URLs prefirmadas de descarga en S3.
    """
    path_params = event.get("pathParameters") or {}
    target_employee_id = path_params.get("employee_id")

    if not target_employee_id:
        return error(400, "El parámetro de ruta 'employee_id' es obligatorio")

    try:
        uuid.UUID(str(target_employee_id))
    except ValueError:
        return error(400, "El formato de 'employee_id' debe ser un UUID válido")

    # Aislamiento RBAC: un EMPLOYEE solo accede a su propio historial salarial
    if role == "EMPLOYEE" and str(auth_employee_id) != str(target_employee_id):
        return error(403, "No tiene permisos para consultar las boletas de pago de otro empleado")

    query_params = event.get("queryStringParameters") or {}
    try:
        page = max(1, int(query_params.get("page", 1)))
        limit = min(50, max(1, int(query_params.get("limit", 12))))
    except ValueError:
        return error(400, "Los parámetros 'page' y 'limit' deben ser enteros positivos")

    offset = (page - 1) * limit

    # 1. Contar total de boletas históricas del empleado
    cursor.execute(
        """
        SELECT COUNT(*) AS total
        FROM pay_slips
        WHERE employee_id = %s;
        """,
        (str(target_employee_id),)
    )
    total_items = int(cursor.fetchone()["total"])
    total_pages = math.ceil(total_items / limit) if total_items > 0 else 1

    # 2. Obtener historial ordenado cronológicamente por periodo descendente
    cursor.execute(
        """
        SELECT
            ps.pay_slip_id,
            ps.period_id,
            pp.period_name,
            pp.is_closed,
            ps.employee_id,
            ps.base_salary,
            ps.deductions,
            ps.net_pay,
            ps.s3_slip_key,
            ps.generated_at
        FROM pay_slips ps
        INNER JOIN payroll_periods pp ON ps.period_id = pp.period_id
        WHERE ps.employee_id = %s
        ORDER BY pp.period_name DESC, ps.generated_at DESC
        LIMIT %s OFFSET %s;
        """,
        (str(target_employee_id), limit, offset)
    )
    rows = cursor.fetchall()

    pay_slips = []
    for row in rows:
        s3_key = row.get("s3_slip_key")
        download_url = None
        if s3_key and s3_key.startswith(f"{tenant_id}/payroll/slips/"):
            download_url = generate_download_presigned_url(
                bucket_name=S3_BUCKET_NAME,
                key=s3_key,
                expires_in=900
            )

        pay_slips.append({
            "paySlipId": str(row["pay_slip_id"]),
            "periodId": str(row["period_id"]),
            "period": row["period_name"],
            "isClosed": row["is_closed"],
            "baseSalary": float(row["base_salary"]),
            "deductions": float(row["deductions"]),
            "netPay": float(row["net_pay"]),
            "s3SlipKey": s3_key,
            "downloadUrl": download_url,
            "generatedAt": row["generated_at"].isoformat() if row["generated_at"] else None
        })

    return success(200, {
        "employeeId": str(target_employee_id),
        "paySlips": pay_slips,
        "pagination": {
            "page": page,
            "limit": limit,
            "totalItems": total_items,
            "totalPages": total_pages
        }
    })
