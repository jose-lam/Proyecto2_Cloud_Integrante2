import sys
import os
import json

for rel_path in ("../", "../../../"):
    abs_path = os.path.abspath(os.path.join(os.path.dirname(__file__), rel_path))
    if abs_path not in sys.path:
        sys.path.append(abs_path)

from shared.middlewares.acl_middleware import require_roles, enforce_self_or_admin
from shared.middlewares.db_tenant_middleware import with_tenant_db
from shared.utils.response import success, error

ADMIN_ONLY_FIELDS = {"role", "departmentId", "status"}


@require_roles(allowed_roles=["ADMIN", "HR_MANAGER", "EMPLOYEE"])
@with_tenant_db
def lambda_handler(event, context, conn, cursor, tenant_id, role, auth_employee_id):
    path_params = event.get("pathParameters") or {}
    target_employee_id = path_params.get("employee_id") or path_params.get("id")

    if not target_employee_id:
        return error(400, "El parámetro 'employee_id' en la ruta es obligatorio")

    # Validación ACL horizontal: EMPLOYEE solo puede editar su propio registro
    acl_violation = enforce_self_or_admin(role, auth_employee_id, target_employee_id)
    if acl_violation:
        return acl_violation

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return error(400, "El cuerpo de la petición debe ser un JSON válido")

    # Evitar escalamiento de privilegios si el solicitante tiene rol EMPLOYEE
    if str(role).upper() == "EMPLOYEE":
        forbidden_fields = ADMIN_ONLY_FIELDS.intersection(body.keys())
        if forbidden_fields:
            return error(
                403,
                "Acceso denegado: un empleado no puede modificar su rol, departamento o estado",
                details={"forbiddenFields": sorted(forbidden_fields)}
            )

    field_mapping = {
        "firstName": "first_name",
        "lastName": "last_name",
        "email": "email",
        "departmentId": "department_id",
        "role": "role",
        "status": "status"
    }

    updates = []
    values = []
    for json_key, db_column in field_mapping.items():
        if json_key in body and body[json_key] is not None:
            updates.append(f"{db_column} = %s")
            values.append(body[json_key])

    if not updates:
        return error(400, "No se enviaron campos válidos para actualizar")

    values.append(target_employee_id)

    cursor.execute(
        f"""
        UPDATE employees
        SET {", ".join(updates)}
        WHERE employee_id = %s
        RETURNING employee_id, department_id, first_name, last_name, email, role, hire_date, status;
        """,
        tuple(values)
    )
    updated_employee = cursor.fetchone()

    if not updated_employee:
        return error(404, f"Empleado '{target_employee_id}' no encontrado en el tenant '{tenant_id}'")

    return success(200, {
        "message": "Empleado actualizado exitosamente",
        "employee": updated_employee
    })
