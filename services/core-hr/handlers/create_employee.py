import sys
import os
import json
import boto3

for rel_path in ("../", "../../../"):
    abs_path = os.path.abspath(os.path.join(os.path.dirname(__file__), rel_path))
    if abs_path not in sys.path:
        sys.path.append(abs_path)

from shared.middlewares.acl_middleware import require_roles
from shared.middlewares.db_tenant_middleware import with_tenant_db
from shared.utils.response import success, error

sns_client = boto3.client("sns")
SNS_HR_EVENTS_ARN = os.environ.get("SNS_HR_EVENTS_ARN", "[FALTA_INTEGRANTE_4_ARN_SNS_HR_EVENTS]")


@require_roles(allowed_roles=["ADMIN", "HR_MANAGER"])
@with_tenant_db
def lambda_handler(event, context, conn, cursor, tenant_id, role, employee_id):
    try:
        body = json.loads(event.get("body") or "{}")
        first_name = body.get("firstName")
        last_name = body.get("lastName")
        email = body.get("email")
        department_id = body.get("departmentId")
        salary = body.get("salary")
        contract_type = body.get("contractType")
        hire_date = body.get("hireDate")
        emp_role = body.get("role", "EMPLOYEE")

        if not all([first_name, last_name, email, department_id, salary, contract_type, hire_date]):
            return error(400, "Faltan campos obligatorios para la creacion del empleado")

        # 1. Insertar empleado en el esquema del tenant activo
        cursor.execute(
            """
            INSERT INTO employees (department_id, first_name, last_name, email, role, hire_date, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'ACTIVE')
            RETURNING employee_id, department_id, first_name, last_name, email, role, hire_date, status, created_at;
            """,
            (department_id, first_name, last_name, email, emp_role, hire_date)
        )
        new_employee = cursor.fetchone()
        emp_id = str(new_employee["employee_id"])

        # 2. Insertar contrato inicial
        cursor.execute(
            """
            INSERT INTO contracts (employee_id, salary, start_date, contract_type)
            VALUES (%s, %s, %s, %s)
            RETURNING contract_id;
            """,
            (emp_id, salary, hire_date, contract_type)
        )

        # 3. Publicar evento SNS compatible con el contrato de hcm-events
        if SNS_HR_EVENTS_ARN and not SNS_HR_EVENTS_ARN.startswith("[FALTA_"):
            sns_payload = {
                "eventType": "employee.created",
                "eventId": str(uuid.uuid4()),
                "occurredAt": datetime.now(timezone.utc).isoformat(),
                "tenantId": tenant_id,
                "employeeId": emp_id,
                "email": email,
                "salary": float(salary),
                "hireDate": str(hire_date)
            }
            sns_client.publish(
                TopicArn=SNS_HR_EVENTS_ARN,
                Message=json.dumps(sns_payload),
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

        return success(201, {
            "message": "Empleado y contrato creados exitosamente",
            "employee": new_employee
        })
    except json.JSONDecodeError:
        return error(400, "El cuerpo de la petición debe ser un JSON válido")
    except Exception as e:
        return error(500, "Error en la transaccion de creacion de empleado", details=str(e))
