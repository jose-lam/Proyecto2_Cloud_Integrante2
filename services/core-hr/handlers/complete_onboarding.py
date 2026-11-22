import json
import os
import uuid
import logging
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

import boto3

from shared.middlewares.acl_middleware import require_roles
from shared.middlewares.db_tenant_middleware import with_tenant_db
from shared.utils.response import success, error

logger = logging.getLogger()
logger.setLevel(logging.INFO)

CONTRACT_TYPES = {"FULL_TIME", "PART_TIME", "CONTRACTOR"}
SNS_ARN = os.environ.get("SNS_HR_EVENTS_ARN", "")


@require_roles(allowed_roles=["ADMIN", "HR_MANAGER"])
@with_tenant_db
def lambda_handler(event, context, conn, cursor, tenant_id, role, auth_employee_id):
    try:
        body = json.loads(event.get("body") or "{}")
        if not isinstance(body, dict):
            return error(400, "El body debe ser un objeto JSON")
    except (TypeError, json.JSONDecodeError):
        return error(400, "JSON inválido")

    try:
        employee_id = str(uuid.UUID(
            str((event.get("pathParameters") or {}).get("id", ""))
        ))

        department_id = str(uuid.UUID(str(body["departmentId"])))

        hire_raw = body["hireDate"]
        if not isinstance(hire_raw, str) or len(hire_raw) != 10:
            raise ValueError("hireDate debe ser YYYY-MM-DD")
        hire_date = date.fromisoformat(hire_raw)

        salary = Decimal(str(body["salary"]))
        if (
            not salary.is_finite()
            or salary <= 0
            or salary >= Decimal("100000000")
            or salary != salary.quantize(Decimal("0.01"))
        ):
            raise ValueError("Salario fuera de rango o con más de 2 decimales")

        contract_type = str(body["contractType"]).strip().upper()
        if contract_type not in CONTRACT_TYPES:
            raise ValueError("Tipo de contrato inválido")

    except (KeyError, ValueError, TypeError, InvalidOperation) as exc:
        return error(400, "Datos de onboarding inválidos", details=str(exc))

    try:
        cursor.execute(
            """
            SELECT employee_id, first_name, last_name, email,
                   status, source_candidate_id
            FROM employees
            WHERE employee_id = %s
            FOR UPDATE
            """,
            (employee_id,)
        )

        employee = cursor.fetchone()

        if not employee:
            return error(404, "Empleado no encontrado")

        if employee["status"] != "PENDING_ONBOARDING":
            return error(409, "El empleado no está pendiente de onboarding")

        if not employee["source_candidate_id"]:
            return error(409, "El empleado no proviene de Recruitment")

        cursor.execute(
            "SELECT department_id FROM departments WHERE department_id = %s",
            (department_id,)
        )

        if not cursor.fetchone():
            return error(404, "Departamento no encontrado en este tenant")

        cursor.execute(
            "SELECT COUNT(*) AS total FROM contracts WHERE employee_id = %s",
            (employee_id,)
        )

        if cursor.fetchone()["total"] != 0:
            return error(409, "El empleado ya tiene un contrato")

        cursor.execute(
            """
            UPDATE employees
            SET department_id = %s,
                hire_date = %s,
                status = 'ACTIVE'
            WHERE employee_id = %s
              AND status = 'PENDING_ONBOARDING'
            RETURNING employee_id
            """,
            (department_id, hire_date, employee_id)
        )

        if not cursor.fetchone():
            raise RuntimeError("No se pudo actualizar el estado")

        cursor.execute(
            """
            INSERT INTO contracts (
                employee_id, salary, start_date, contract_type
            )
            VALUES (%s, %s, %s, %s)
            RETURNING contract_id
            """,
            (employee_id, salary, hire_date, contract_type)
        )

        contract_id = str(cursor.fetchone()["contract_id"])

        # Ambas operaciones quedan confirmadas juntas.
        conn.commit()

    except Exception:
        conn.rollback()
        logger.exception("Error al completar onboarding")
        return error(500, "No se pudo completar el onboarding")

    # Publicar solo después de confirmar la transacción.
    sns_published = False

    if SNS_ARN.startswith("arn:aws:sns:"):
        payload = {
            "eventType": "employee.created",
            "eventId": str(uuid.uuid4()),
            "occurredAt": datetime.now(timezone.utc).isoformat(),
            "tenantId": tenant_id,
            "employeeId": employee_id,
            "email": employee["email"],
            "salary": float(salary),
            "hireDate": hire_date.isoformat()
        }

        try:
            boto3.client("sns").publish(
                TopicArn=SNS_ARN,
                Message=json.dumps(payload),
                MessageAttributes={
                    "eventType": {
                        "DataType": "String",
                        "StringValue": "employee.created"
                    },
                    "tenantId": {
                        "DataType": "String",
                        "StringValue": tenant_id
                    }
                }
            )
            sns_published = True
        except Exception:
            logger.exception("Onboarding completado, pero falló SNS")

    return success(200, {
        "message": "Onboarding completado exitosamente",
        "employeeId": employee_id,
        "candidateId": employee["source_candidate_id"],
        "status": "ACTIVE",
        "departmentId": department_id,
        "hireDate": hire_date.isoformat(),
        "contractId": contract_id,
        "contractType": contract_type,
        "salary": float(salary),
        "snsPublished": sns_published
    })
