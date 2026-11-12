import sys
import os
import math
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))

from shared.middlewares.db_tenant_middleware import with_tenant_db
from shared.utils.response import success, error

@with_tenant_db
def lambda_handler(event, context, conn, cursor, tenant_id, role, employee_id):
    try:
        params = event.get('queryStringParameters') or {}
        page = max(1, int(params.get('page', 1)))
        limit = max(1, min(100, int(params.get('limit', 50))))
        status = params.get('status')
        search = params.get('search')

        offset = (page - 1) * limit
        where_clauses = []
        query_params = []

        if status:
            where_clauses.append("e.status = %s")
            query_params.append(status)

        if search:
            where_clauses.append("(e.first_name ILIKE %s OR e.last_name ILIKE %s OR e.email ILIKE %s)")
            search_pattern = f"%{search}%"
            query_params.extend([search_pattern, search_pattern, search_pattern])

        where_stmt = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        # Consulta de conteo total
        cursor.execute(f"SELECT COUNT(*) as total FROM employees e {where_stmt};", query_params)
        total_count = cursor.fetchone()['total']

        # Consulta paginada con JOINs
        data_query = f"""
            SELECT
                e.employee_id, e.first_name, e.last_name, e.email, e.role, e.hire_date, e.status, e.created_at,
                d.department_id, d.name AS department_name,
                c.contract_id, c.salary, c.contract_type, c.start_date AS contract_start_date
            FROM employees e
            LEFT JOIN departments d ON e.department_id = d.department_id
            LEFT JOIN contracts c ON e.employee_id = c.employee_id
            {where_stmt}
            ORDER BY e.created_at DESC
            LIMIT %s OFFSET %s;
        """
        cursor.execute(data_query, query_params + [limit, offset])
        items = cursor.fetchall()

        total_pages = math.ceil(total_count / limit) if limit > 0 else 0

        return success(200, {
            "items": items,
            "pagination": {
                "total": total_count,
                "page": page,
                "limit": limit,
                "totalPages": total_pages
            }
        })
    except Exception as e:
        return error(500, "Error al consultar empleados", details=str(e))
