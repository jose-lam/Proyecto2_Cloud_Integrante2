import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))

from shared.middlewares.db_tenant_middleware import with_tenant_db
from shared.utils.response import success, error

@with_tenant_db
def lambda_handler(event, context, conn, cursor, tenant_id, role, employee_id):
    try:
        path_params = event.get('pathParameters') or {}
        emp_id = path_params.get('id')

        if not emp_id:
            return error(400, "El parametro 'id' es requerido")

        cursor.execute(
            """
            SELECT
                e.employee_id, e.first_name, e.last_name, e.email, e.role, e.hire_date, e.status, e.created_at,
                d.department_id, d.name AS department_name,
                c.contract_id, c.salary, c.contract_type, c.start_date, c.end_date
            FROM employees e
            LEFT JOIN departments d ON e.department_id = d.department_id
            LEFT JOIN contracts c ON e.employee_id = c.employee_id
            WHERE e.employee_id = %s;
            """,
            (emp_id,)
        )
        employee = cursor.fetchone()

        if not employee:
            return error(404, "Empleado no encontrado en el esquema del tenant actual")

        return success(200, employee)
    except Exception as e:
        return error(500, "Error al obtener detalle del empleado", details=str(e))
