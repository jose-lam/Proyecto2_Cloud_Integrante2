import sys
import os
import json

for rel_path in ("../", "../../../"):
    abs_path = os.path.abspath(os.path.join(os.path.dirname(__file__), rel_path))
    if abs_path not in sys.path:
        sys.path.append(abs_path)

from shared.middlewares.acl_middleware import require_roles
from shared.middlewares.db_tenant_middleware import with_tenant_db
from shared.utils.response import success, error


@require_roles(allowed_roles=["ADMIN", "HR_MANAGER"])
@with_tenant_db
def lambda_handler(event, context, conn, cursor, tenant_id, role, employee_id):
    try:
        body = json.loads(event.get("body") or "{}")
        name = str(body.get("name") or "").strip()
        budget = body.get("budget")

        if not name or budget is None:
            return error(400, "Campos 'name' y 'budget' son obligatorios")

        cursor.execute(
            """
            INSERT INTO departments (name, budget)
            VALUES (%s, %s)
            RETURNING department_id, name, budget, created_at;
            """,
            (name, budget)
        )
        new_department = cursor.fetchone()
        return success(201, new_department)
    except json.JSONDecodeError:
        return error(400, "El cuerpo de la petición debe ser un JSON válido")
    except Exception as e:
        return error(500, "Error al crear el departamento", details=str(e))
