import json
import logging
import os
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional
from uuid import UUID

import psycopg2

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ALLOWED_SCHEMAS = {"tenant_a", "tenant_b", "tenant_c"}

UPSERT_SALARY_PROFILE_SQL = """
INSERT INTO employee_salary_profiles (employee_id, email, base_salary, hire_date, is_active)
VALUES (%s, %s, %s, %s, TRUE)
ON CONFLICT (employee_id) DO UPDATE
SET email = EXCLUDED.email,
    base_salary = EXCLUDED.base_salary,
    is_active = TRUE,
    synced_at = CURRENT_TIMESTAMP;
"""


class PermanentPayloadError(ValueError):
    """Error de formato o contrato inválido que no debe reintentarse en SQS."""


def _get_db_connection():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", 5432)),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        connect_timeout=5,
    )


def _resolve_tenant_schema(raw_tenant_id: Any) -> str:
    """Normaliza y valida el tenant_id contra la lista blanca de esquemas."""
    if not raw_tenant_id or not isinstance(raw_tenant_id, str):
        raise PermanentPayloadError("Campo 'tenant_id' ausente o inválido")

    clean = raw_tenant_id.strip().lower()
    schema_name = clean if clean.startswith("tenant_") else f"tenant_{clean}"

    if schema_name not in ALLOWED_SCHEMAS:
        raise PermanentPayloadError(f"Tenant no autorizado: {raw_tenant_id}")

    return schema_name


def _unwrap_sns_message(record: Dict[str, Any]) -> Dict[str, Any]:
    """Desenvuelve el envelope de SNS dentro de record['body'] de SQS."""
    raw_body = record.get("body")
    if not raw_body:
        raise PermanentPayloadError("El registro SQS no contiene 'body'")

    try:
        envelope = json.loads(raw_body) if isinstance(raw_body, str) else raw_body
    except json.JSONDecodeError as exc:
        raise PermanentPayloadError(f"JSON inválido en SQS body: {exc}") from exc

    if isinstance(envelope, dict) and "Message" in envelope:
        raw_message = envelope["Message"]
        try:
            payload = (
                json.loads(raw_message)
                if isinstance(raw_message, str)
                else raw_message
            )
        except json.JSONDecodeError as exc:
            raise PermanentPayloadError(f"JSON inválido en SNS Message: {exc}") from exc
    else:
        payload = envelope

    if not isinstance(payload, dict):
        raise PermanentPayloadError("El payload del evento debe ser un objeto JSON")

    return payload


def _parse_and_validate_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Extrae y valida { tenant_id, employee_id, email, salary, hire_date }."""
    event_type = payload.get("event_type") or payload.get("eventType")
    if event_type and event_type != "employee.created":
        raise PermanentPayloadError(f"Tipo de evento inesperado: {event_type}")

    raw_tenant_id = payload.get("tenant_id") or payload.get("tenantId")
    schema_name = _resolve_tenant_schema(raw_tenant_id)

    raw_employee_id = payload.get("employee_id") or payload.get("employeeId")
    if not raw_employee_id:
        raise PermanentPayloadError("Campo 'employee_id' requerido")
    try:
        employee_id = str(UUID(str(raw_employee_id)))
    except ValueError as exc:
        raise PermanentPayloadError(f"UUID inválido en 'employee_id': {raw_employee_id}") from exc

    email = payload.get("email")
    if not email or not isinstance(email, str) or "@" not in email:
        raise PermanentPayloadError(f"Campo 'email' inválido: {email}")

    raw_salary = (
        payload.get("salary")
        if payload.get("salary") is not None
        else payload.get("base_salary") or payload.get("baseSalary")
    )
    if raw_salary is None:
        raise PermanentPayloadError("Campo 'salary' requerido")
    try:
        salary = Decimal(str(raw_salary))
    except InvalidOperation as exc:
        raise PermanentPayloadError(f"Valor numérico inválido en 'salary': {raw_salary}") from exc
    if salary <= 0:
        raise PermanentPayloadError(f"El salario debe ser mayor a 0: {salary}")

    raw_hire_date = payload.get("hire_date") or payload.get("hireDate")
    if not raw_hire_date:
        raise PermanentPayloadError("Campo 'hire_date' requerido")
    try:
        hire_date = date.fromisoformat(str(raw_hire_date)[:10]).isoformat()
    except ValueError as exc:
        raise PermanentPayloadError(f"Formato de fecha inválido en 'hire_date': {raw_hire_date}") from exc

    return {
        "schema_name": schema_name,
        "employee_id": employee_id,
        "email": email.strip().lower(),
        "salary": salary,
        "hire_date": hire_date,
    }


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, List[Dict[str, str]]]:
    records = event.get("Records", [])
    if not records:
        return {"batchItemFailures": []}

    batch_item_failures: List[Dict[str, str]] = []
    conn: Optional[Any] = None
    cursor: Optional[Any] = None

    try:
        conn = _get_db_connection()
        cursor = conn.cursor()

        for record in records:
            msg_id = record.get("messageId", "unknown")
            try:
                payload = _unwrap_sns_message(record)
                data = _parse_and_validate_payload(payload)

                # Conmutación al esquema aislado del tenant (validado contra lista blanca)
                cursor.execute(f"SET search_path TO {data['schema_name']}, public;")

                cursor.execute(
                    UPSERT_SALARY_PROFILE_SQL,
                    (
                        data["employee_id"],
                        data["email"],
                        data["salary"],
                        data["hire_date"],
                    ),
                )
                conn.commit()

                logger.info(
                    "Perfil salarial sincronizado | tenant=%s employee_id=%s messageId=%s",
                    data["schema_name"],
                    data["employee_id"],
                    msg_id,
                )

            except PermanentPayloadError as perm_err:
                if conn:
                    conn.rollback()
                # Se descarta el mensaje malformado (no se agrega a batchItemFailures)
                logger.error(
                    "Mensaje descartado por payload inválido | messageId=%s error=%s",
                    msg_id,
                    str(perm_err),
                )

            except Exception as exc:
                if conn:
                    conn.rollback()
                logger.exception(
                    "Error transitorio procesando employee.created | messageId=%s error=%s",
                    msg_id,
                    str(exc),
                )
                batch_item_failures.append({"itemIdentifier": msg_id})

            finally:
                if cursor and conn and not conn.closed:
                    try:
                        cursor.execute("SET search_path TO public;")
                        conn.commit()
                    except Exception:
                        conn.rollback()

    except Exception as conn_exc:
        # Si falla la conexión inicial a RDS, se devuelven todos los mensajes del lote para reintento
        logger.exception("Error de conexión a RDS PostgreSQL: %s", str(conn_exc))
        return {
            "batchItemFailures": [
                {"itemIdentifier": r["messageId"]}
                for r in records
                if r.get("messageId")
            ]
        }

    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    return {"batchItemFailures": batch_item_failures}
