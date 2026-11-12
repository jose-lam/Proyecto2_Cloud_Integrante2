import os
import sys
import json
from unittest.mock import MagicMock, patch
import pytest

# Asegurar resolución de imports desde la raíz del repositorio
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from shared.middlewares.db_tenant_middleware import with_tenant_db
from shared.utils.response import success, error


def _build_api_gateway_event(tenant_id, role="ADMIN", employee_id="emp-admin-01", path_params=None):
    """Construye un evento simulado de API Gateway con claims del Custom Authorizer."""
    authorizer = {}
    if tenant_id is not None:
        authorizer["tenant_id"] = tenant_id
    if role is not None:
        authorizer["role"] = role
    if employee_id is not None:
        authorizer["employee_id"] = employee_id

    return {
        "requestContext": {
            "authorizer": authorizer
        },
        "pathParameters": path_params or {},
        "queryStringParameters": {}
    }


@with_tenant_db
def _sample_protected_handler(event, context, conn, cursor, tenant_id, role, employee_id):
    """Handler de prueba que ejecuta una consulta simple dentro del esquema aislado."""
    cursor.execute("SELECT current_schema();")
    row = cursor.fetchone()
    return success(200, {
        "tenant_id": tenant_id,
        "role": role,
        "schema_result": row
    })


@with_tenant_db
def _sample_failing_handler(event, context, conn, cursor, tenant_id, role, employee_id):
    """Handler de prueba que falla a mitad de transacción para verificar limpieza en finally."""
    cursor.execute("SELECT 1;")
    raise RuntimeError("Fallo simulado en lógica de negocio")


@with_tenant_db
def _get_employee_by_id_handler(event, context, conn, cursor, tenant_id, role, employee_id):
    """Handler representativo de GET /employees/{employee_id} aislado por search_path."""
    target_id = (event.get("pathParameters") or {}).get("employee_id")
    if not target_id:
        return error(400, "El parámetro employee_id es obligatorio")

    cursor.execute(
        """
        SELECT employee_id, first_name, last_name, email, status
        FROM employees
        WHERE employee_id = %s;
        """,
        (target_id,)
    )
    employee = cursor.fetchone()

    if not employee:
        return error(404, f"Empleado '{target_id}' no encontrado en el tenant actual")

    return success(200, employee)


# ==============================================================================
# PRUEBA 1: Validación de SET search_path TO tenant_a, public; y reset a public
# ==============================================================================
@patch("shared.middlewares.db_tenant_middleware.psycopg2.connect")
def test_middleware_sets_and_resets_search_path(mock_connect):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {"current_schema": "tenant_a"}
    mock_conn.cursor.return_value = mock_cursor
    mock_connect.return_value = mock_conn

    event = _build_api_gateway_event(tenant_id="tenant_a", role="HR_MANAGER", employee_id="emp-100")
    response = _sample_protected_handler(event, None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["tenant_id"] == "tenant_a"

    executed_sql = [call.args[0] for call in mock_cursor.execute.call_args_list]
    assert executed_sql[0] == "SET search_path TO tenant_a, public;"
    assert "SELECT current_schema();" in executed_sql
    assert executed_sql[-1] == "SET search_path TO public;"

    mock_conn.commit.assert_called_once()
    mock_cursor.close.assert_called_once()
    mock_conn.close.assert_called_once()


@patch("shared.middlewares.db_tenant_middleware.psycopg2.connect")
def test_middleware_resets_search_path_even_on_handler_exception(mock_connect):
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_connect.return_value = mock_conn

    event = _build_api_gateway_event(tenant_id="tenant_a", role="ADMIN")
    response = _sample_failing_handler(event, None)

    assert response["statusCode"] == 500
    executed_sql = [call.args[0] for call in mock_cursor.execute.call_args_list]
    assert executed_sql[0] == "SET search_path TO tenant_a, public;"
    assert executed_sql[-1] == "SET search_path TO public;"

    mock_conn.rollback.assert_called_once()
    mock_cursor.close.assert_called_once()
    mock_conn.close.assert_called_once()


# ==============================================================================
# PRUEBA 2: Rechazo de inyección SQL en tenant_id ANTES de abrir conexión o consultar
# ==============================================================================
@pytest.mark.parametrize(
    "malicious_tenant_id",
    [
        "tenant_a; DROP TABLE employees; --",
        "tenant_a, tenant_b",
        "tenant_a' OR '1'='1",
        "public; SET search_path TO tenant_b; --",
        "tenant_a\nSET search_path TO tenant_c;",
        "../tenant_b",
        "",
        None,
        "tenant_inexistente",
    ],
)
@patch("shared.middlewares.db_tenant_middleware.psycopg2.connect")
def test_sql_injection_in_tenant_id_rejected_before_db_query(mock_connect, malicious_tenant_id):
    event = _build_api_gateway_event(tenant_id=malicious_tenant_id, role="ADMIN")
    response = _sample_protected_handler(event, None)

    assert response["statusCode"] == 401
    body = json.loads(response["body"])
    assert "Tenant no autorizado" in body["message"]

    # Garantiza que jamás se abrió conexión a PostgreSQL ni se ejecutó SQL
    mock_connect.assert_not_called()


# ==============================================================================
# PRUEBA 3: Aislamiento cruzado (employee_id de tenant_a consultado con token de tenant_b -> 404)
# ==============================================================================
@patch("shared.middlewares.db_tenant_middleware.psycopg2.connect")
def test_cross_tenant_employee_lookup_returns_404(mock_connect):
    target_employee_id = "11111111-1111-1111-1111-111111111111"

    # Estado simulado aislado por esquema en PostgreSQL
    schemas_db = {
        "tenant_a": {
            target_employee_id: {
                "employee_id": target_employee_id,
                "first_name": "Valeria",
                "last_name": "Mendoza",
                "email": "valeria.mendoza@tenanta.com",
                "status": "ACTIVE",
            }
        },
        "tenant_b": {},
        "tenant_c": {},
    }

    active_state = {"schema": "public", "last_result": None}

    def fake_execute(query, params=None):
        sql = query.strip()
        if sql.startswith("SET search_path TO "):
            # Extrae el esquema principal de 'SET search_path TO tenant_x, public;'
            schema_part = sql.replace("SET search_path TO ", "").split(",")[0].strip()
            active_state["schema"] = schema_part
            active_state["last_result"] = None
        elif "FROM employees" in sql and params:
            emp_id = params[0]
            current_schema_table = schemas_db.get(active_state["schema"], {})
            active_state["last_result"] = current_schema_table.get(emp_id)

    mock_cursor = MagicMock()
    mock_cursor.execute.side_effect = fake_execute
    mock_cursor.fetchone.side_effect = lambda: active_state["last_result"]

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_connect.return_value = mock_conn

    # 1. Consulta legítima desde tenant_a -> HTTP 200
    event_tenant_a = _build_api_gateway_event(
        tenant_id="tenant_a",
        role="ADMIN",
        path_params={"employee_id": target_employee_id},
    )
    resp_a = _get_employee_by_id_handler(event_tenant_a, None)
    assert resp_a["statusCode"] == 200
    assert json.loads(resp_a["body"])["email"] == "valeria.mendoza@tenanta.com"

    # 2. Intento de lectura del mismo employee_id usando token de tenant_b -> HTTP 404
    event_tenant_b = _build_api_gateway_event(
        tenant_id="tenant_b",
        role="ADMIN",
        path_params={"employee_id": target_employee_id},
    )
    resp_b = _get_employee_by_id_handler(event_tenant_b, None)
    assert resp_b["statusCode"] == 404
    assert "no encontrado" in json.loads(resp_b["body"])["message"].lower()
