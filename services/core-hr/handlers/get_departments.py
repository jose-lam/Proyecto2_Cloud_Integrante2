import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))

from shared.middlewares.db_tenant_middleware import with_tenant_db
from shared.utils.response import success, error

@with_tenant_db
def lambda_handler(event, context, conn, cursor, tenant_id, role, employee_id):
    try:
        cursor.execute("SELECT department_id, name, budget, created_at FROM departments ORDER BY name ASC;")
        departments = cursor.fetchall()
        return success(200, departments)
    except Exception as e:
        return error(500, "Error al obtener departamentos", details=str(e))
