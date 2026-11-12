import json
import logging
import os
from datetime import date
from typing import Any, Dict, List, Optional
from uuid import UUID

import psycopg2

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ALLOWED_SCHEMAS = {"tenant_a", "tenant_b", "tenant_c"}

INSERT_UNPAID_LEAVE_SQL = """
INSERT INTO unpaid_leaves_ledger (leave_id, employee_id, days_unpaid, period_target, applied)
VALUES (%s, %s, %s, %s, FALSE)
ON CONFLICT (leave_id) DO NOTHING;
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
    """Extrae y valida { tenant_id, leave_id, employee_id, days_unpaid, start_date }."""
    event_type = payload.get("event_type") or payload.get("eventType")
    if event_type and event_type != "leave.approved":
        raise PermanentPayloadError(f"Tipo de evento inesperado: {event_type}")

    raw_tenant_id = payload.get("tenant_id") or payload.get("tenantId")
    schema_name = _resolve_tenant_schema(raw_tenant_id)

    raw_leave_id = payload.get("leave_id") or payload.get("leaveId")
    if not raw_leave_id:
        raise PermanentPayloadError("Campo 'leave_id' requerido")
    try:
        leave_id = str(UUID(str(raw_leave_id)))
    except ValueError as exc:
        raise PermanentPayloadError(f"UUID inválido en 'leave_id': {raw_leave_id}") from exc

    raw_employee_id = payload.get("employee_id") or payload.get("employeeId")
    if not raw_employee_id:
        raise PermanentPayloadError("Campo 'employee_id' requerido")
    try:
        employee_id = str(UUID(str(raw_employee_id)))
    except ValueError as exc:
        raise PermanentPayloadError(f"UUID inválido en 'employee_id': {raw_employee_id}") from exc

    raw_days_unpaid = (
        payload.get("days_unpaid")
        if payload.get("days_unpaid") is not None
        else payload.get("daysUnpaid")
    )
    if raw_days_unpaid is None:
        raise PermanentPayloadError("Campo 'days_unpaid' requerido")
    try:
        days_unpaid = int(raw_days_unpaid)
    except (TypeError, ValueError) as exc:
        raise PermanentPayloadError(f"Valor entero inválido en 'days_unpaid': {raw_days_unpaid}") from exc
    if days_unpaid < 0:
        raise PermanentPayloadError(f"El campo 'days_unpaid' no puede ser negativo: {days_unpaid}")

    raw_start_date = payload.get("start_date") or payload.get("startDate")
    if not raw_start_date:
        raise PermanentPayloadError("Campo 'start_date' requerido")
    try:
        parsed_start = date.fromisoformat(str(raw_start_date)[:10])
    except ValueError as exc:
        raise PermanentPayloadError(f"Formato de fecha inválido en 'start_date': {raw_start_date}") from exc

    period_target = parsed_start.strftime("%Y-%m")

    return {
        "schema_name": schema_name,
        "leave_id": leave_id,
        "employee_id": employee_id,
        "days_unpaid": days_unpaid,
        "start_date": parsed_start.isoformat(),
        "period_target": period_target,
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

                # Licencias pagadas (VACATION/SICK) llegan con days_unpaid = 0: no generan descuento
                if data["days_unpaid"] == 0:
                    logger.info(
                        "Licencia aprobada sin días no pagados (days_unpaid=0), omitida | tenant=%s leave_id=%s messageId=%s",
                        data["schema_name"],
                        data["leave_id"],
                        msg_id,
                    )
                    continue

                # Conmutación al esquema aislado del tenant (validado contra lista blanca)
                cursor.execute(f"SET search_path TO {data['schema_name']}, public;")

                cursor.execute(
                    INSERT_UNPAID_LEAVE_SQL,
                    (
                        data["leave_id"],
                        data["employee_id"],
                        data["days_unpaid"],
                        data["period_target"],
                    ),
                )
                inserted = cursor.rowcount > 0
                conn.commit()

                logger.info(
                    "Licencia no pagada procesada | tenant=%s leave_id=%s employee_id=%s days=%s period=%s inserted=%s messageId=%s",
                    data["schema_name"],
                    data["leave_id"],
                    data["employee_id"],
                    data["days_unpaid"],
                    data["period_target"],
                    inserted,
                    msg_id,
                )

            except PermanentPayloadError as perm_err:
                if conn:
                    conn.rollback()
                logger.error(
                    "Mensaje descartado por payload inválido | messageId=%s error=%s",
                    msg_id,
                    str(perm_err),
                )

            except Exception as exc:
                if conn:
                    conn.rollback()
                logger.exception(
                    "Error transitorio procesando leave.approved | messageId=%s error=%s",
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
