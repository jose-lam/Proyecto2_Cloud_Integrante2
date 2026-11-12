import sys
import json
import os
import re
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import boto3
from botocore.exceptions import ClientError

for rel_path in ("../", "../../../"):
    abs_path = os.path.abspath(os.path.join(os.path.dirname(__file__), rel_path))
    if abs_path not in sys.path:
        sys.path.append(abs_path)

from shared.middlewares.acl_middleware import require_roles
from shared.middlewares.db_tenant_middleware import with_tenant_db
from shared.utils.response import success, error
from shared.utils.s3_helper import build_payslip_s3_key, upload_pdf_bytes
from utils.pdf_slip_generator import generate_pay_slip_pdf

S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME", "[FALTA_INTEGRANTE_1_NOMBRE_BUCKET_S3]")
SNS_PAYROLL_EVENTS_ARN = os.environ.get(
    "SNS_PAYROLL_EVENTS_ARN",
    "[FALTA_INTEGRANTE_4_ARN_SNS_PAYROLL_EVENTS]"
)

PERIOD_REGEX = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
STATUTORY_TAX_RATE = Decimal("0.13")
DAYS_IN_PAYROLL_MONTH = Decimal("30")

_sns_client = boto3.client("sns")


def _round_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _publish_payroll_processed_event(payload: dict) -> bool:
    """Publica el evento de dominio payroll.processed en Amazon SNS."""
    if not SNS_PAYROLL_EVENTS_ARN or SNS_PAYROLL_EVENTS_ARN.startswith("[FALTA_"):
        return False

    try:
        _sns_client.publish(
            TopicArn=SNS_PAYROLL_EVENTS_ARN,
            Subject="payroll.processed",
            Message=json.dumps(payload, default=str),
            MessageAttributes={
                "eventType": {
                    "DataType": "String",
                    "StringValue": "payroll.processed"
                },
                "tenantId": {
                    "DataType": "String",
                    "StringValue": payload["tenantId"]
                }
            }
        )
        return True
    except ClientError:
        return False


@require_roles(allowed_roles=["ADMIN", "HR_MANAGER"])
@with_tenant_db
def lambda_handler(event, context, conn, cursor, tenant_id, role, auth_employee_id):
    """
    POST /payrolls/calculate
    Body esperado: { "period": "2026-11", "generatePdfs": true }
    """
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return error(400, "El cuerpo de la petición debe ser un JSON válido")

    period = str(body.get("period", "")).strip()
    if not PERIOD_REGEX.match(period):
        return error(400, "El campo 'period' es obligatorio y debe tener formato YYYY-MM (ej. 2026-11)")

    generate_pdfs = bool(body.get("generatePdfs", True))

    # 1. Buscar o crear el periodo en payroll_periods (bloqueo FOR UPDATE para concurrencia)
    cursor.execute(
        """
        SELECT period_id, period_name, is_closed, total_paid
        FROM payroll_periods
        WHERE period_name = %s
        FOR UPDATE;
        """,
        (period,)
    )
    period_row = cursor.fetchone()

    if period_row:
        if period_row["is_closed"]:
            return error(409, f"El periodo de nómina '{period}' ya se encuentra cerrado")
        period_id = str(period_row["period_id"])
    else:
        cursor.execute(
            """
            INSERT INTO payroll_periods (period_name, is_closed, total_paid)
            VALUES (%s, FALSE, 0.00)
            RETURNING period_id, period_name, is_closed, total_paid;
            """,
            (period,)
        )
        period_row = cursor.fetchone()
        period_id = str(period_row["period_id"])

    # 2. Leer perfiles salariales desde employee_salary_profiles con fallback a employees + contracts
    cursor.execute(
        """
        WITH latest_contracts AS (
            SELECT DISTINCT ON (c.employee_id)
                c.employee_id,
                c.salary,
                c.contract_type
            FROM contracts c
            WHERE c.start_date <= (to_date(%s || '-01', 'YYYY-MM-DD') + INTERVAL '1 month - 1 day')::date
              AND (c.end_date IS NULL OR c.end_date >= to_date(%s || '-01', 'YYYY-MM-DD'))
            ORDER BY c.employee_id, c.start_date DESC
        )
        SELECT
            COALESCE(esp.employee_id, e.employee_id) AS employee_id,
            COALESCE(esp.email, e.email) AS email,
            COALESCE(e.first_name || ' ' || e.last_name, esp.email) AS full_name,
            COALESCE(esp.base_salary, lc.salary) AS base_salary,
            COALESCE(esp.hire_date, e.hire_date) AS hire_date,
            COALESCE(lc.contract_type, 'FULL_TIME') AS contract_type
        FROM employees e
        LEFT JOIN employee_salary_profiles esp
            ON e.employee_id = esp.employee_id AND esp.is_active = TRUE
        LEFT JOIN latest_contracts lc
            ON e.employee_id = lc.employee_id
        WHERE e.status = 'ACTIVE'
          AND (esp.base_salary IS NOT NULL OR lc.salary IS NOT NULL)
        UNION
        SELECT
            esp.employee_id,
            esp.email,
            esp.email AS full_name,
            esp.base_salary,
            esp.hire_date,
            'FULL_TIME' AS contract_type
        FROM employee_salary_profiles esp
        WHERE esp.is_active = TRUE
          AND NOT EXISTS (
              SELECT 1 FROM employees e WHERE e.employee_id = esp.employee_id
          );
        """,
        (period, period)
    )
    employees_to_pay = cursor.fetchall()

    if not employees_to_pay:
        return error(404, f"No se encontraron empleados activos con perfil salarial para el periodo {period}")

    # 3. Obtener licencias no pagadas del periodo (unpaid_leaves_ledger)
    cursor.execute(
        """
        SELECT
            employee_id,
            COALESCE(SUM(days_unpaid), 0) AS total_unpaid_days
        FROM unpaid_leaves_ledger
        WHERE period_target = %s
        GROUP BY employee_id;
        """,
        (period,)
    )
    unpaid_map = {
        str(row["employee_id"]): int(row["total_unpaid_days"])
        for row in cursor.fetchall()
    }

    total_gross = Decimal("0.00")
    total_deductions_all = Decimal("0.00")
    total_net_paid = Decimal("0.00")
    pdfs_generated_count = 0

    # 4. Calcular liquidación por empleado, upsert en pay_slips y generación opcional de PDF en S3
    for emp in employees_to_pay:
        emp_id = str(emp["employee_id"])
        base_salary = _round_money(Decimal(str(emp["base_salary"])))
        unpaid_days = unpaid_map.get(emp_id, 0)

        raw_leave_deduction = (base_salary / DAYS_IN_PAYROLL_MONTH) * Decimal(str(unpaid_days))
        unpaid_leave_deduction = min(base_salary, _round_money(raw_leave_deduction))

        taxable_base = max(Decimal("0.00"), base_salary - unpaid_leave_deduction)
        statutory_withholding = _round_money(taxable_base * STATUTORY_TAX_RATE)

        total_deductions = _round_money(unpaid_leave_deduction + statutory_withholding)
        net_pay = max(Decimal("0.00"), _round_money(base_salary - total_deductions))

        s3_slip_key = None
        if generate_pdfs:
            pdf_bytes = generate_pay_slip_pdf(
                tenant_id=tenant_id,
                period=period,
                employee_data=emp,
                base_salary=base_salary,
                unpaid_leave_deduction=unpaid_leave_deduction,
                statutory_withholding=statutory_withholding,
                net_pay=net_pay,
                unpaid_days=unpaid_days
            )
            s3_slip_key = build_payslip_s3_key(tenant_id, period_id, emp_id)
            upload_pdf_bytes(S3_BUCKET_NAME, s3_slip_key, pdf_bytes)
            pdfs_generated_count += 1

        cursor.execute(
            """
            INSERT INTO pay_slips (
                period_id,
                employee_id,
                base_salary,
                deductions,
                net_pay,
                s3_slip_key,
                generated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (period_id, employee_id)
            DO UPDATE SET
                base_salary = EXCLUDED.base_salary,
                deductions = EXCLUDED.deductions,
                net_pay = EXCLUDED.net_pay,
                s3_slip_key = COALESCE(EXCLUDED.s3_slip_key, pay_slips.s3_slip_key),
                generated_at = CURRENT_TIMESTAMP
            RETURNING pay_slip_id;
            """,
            (
                period_id,
                emp_id,
                base_salary,
                total_deductions,
                net_pay,
                s3_slip_key
            )
        )

        total_gross += base_salary
        total_deductions_all += total_deductions
        total_net_paid += net_pay

    # 5. Marcar licencias del periodo como aplicadas y actualizar total_paid
    cursor.execute(
        """
        UPDATE unpaid_leaves_ledger
        SET applied = TRUE,
            processed_at = CURRENT_TIMESTAMP
        WHERE period_target = %s
          AND applied = FALSE;
        """,
        (period,)
    )

    cursor.execute(
        """
        UPDATE payroll_periods
        SET total_paid = %s
        WHERE period_id = %s;
        """,
        (_round_money(total_net_paid), period_id)
    )

    conn.commit()

    processed_at = datetime.now(timezone.utc).isoformat()
    event_payload = {
        "eventType": "payroll.processed",
        "eventId": str(uuid.uuid4()),
        "occurredAt": processed_at,
        "tenantId": tenant_id,
        "periodId": period_id,
        "period": period,
        "employeesProcessed": len(employees_to_pay),
        "totalGrossSalary": float(_round_money(total_gross)),
        "totalDeductions": float(_round_money(total_deductions_all)),
        "totalNetPaid": float(_round_money(total_net_paid)),
        "pdfsGenerated": pdfs_generated_count,
        "processedAt": processed_at
    }
    sns_published = _publish_payroll_processed_event(event_payload)

    return success(200, {
        "message": f"Nómina del periodo {period} calculada exitosamente",
        "periodId": period_id,
        "period": period,
        "employeesProcessed": len(employees_to_pay),
        "totalGrossSalary": float(_round_money(total_gross)),
        "totalDeductions": float(_round_money(total_deductions_all)),
        "totalNetPaid": float(_round_money(total_net_paid)),
        "pdfsGenerated": pdfs_generated_count,
        "snsPublished": sns_published,
        "processedAt": processed_at
    })
