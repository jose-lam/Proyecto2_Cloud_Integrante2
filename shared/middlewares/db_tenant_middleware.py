import os
import functools
import psycopg2
from psycopg2.extras import RealDictCursor
from shared.utils.response import error

ALLOWED_TENANTS = {'tenant_a', 'tenant_b', 'tenant_c'}

def with_tenant_db(func):
    """
    Decorador Python para aislamiento multi-tenant en PostgreSQL.
    Valida tenant_id, establece search_path y limpia la conexión en el bloque finally.
    """
    @functools.wraps(func)
    def wrapper(event, context, *args, **kwargs):
        authorizer = event.get('requestContext', {}).get('authorizer', {})
        tenant_id = authorizer.get('tenant_id')
        role = authorizer.get('role')
        employee_id = authorizer.get('employee_id')

        # 1 y 2. Extraer y validar el tenant contra lista blanca
        if not tenant_id or tenant_id not in ALLOWED_TENANTS:
            return error(401, "Tenant no autorizado o invalido")

        conn = None
        cursor = None
        try:
            # 3. Conexión a PostgreSQL
            conn = psycopg2.connect(
                host=os.environ.get('DB_HOST'),
                port=int(os.environ.get('DB_PORT', 5432)),
                dbname=os.environ.get('DB_NAME'),
                user=os.environ.get('DB_USER'),
                password=os.environ.get('DB_PASSWORD')
            )
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            # Conmutación aislada de esquema (validado contra lista blanca)
            cursor.execute(f"SET search_path TO {tenant_id}, public;")

            # 4. Invocación del handler con argumentos inyectados
            result = func(event, context, conn, cursor, tenant_id, role, employee_id, *args, **kwargs)
            conn.commit()
            return result
        except Exception as e:
            if conn:
                conn.rollback()
            return error(500, "Error interno de base de datos", details=str(e))
        finally:
            # 5. Limpieza garantizada de la sesión de base de datos
            if cursor:
                try:
                    cursor.execute("SET search_path TO public;")
                except Exception:
                    pass
                cursor.close()
            if conn:
                conn.close()

    return wrapper
