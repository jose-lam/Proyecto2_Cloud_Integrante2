import json
import logging
import os

import psycopg2
from psycopg2 import sql

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ALLOWED_TENANTS = {"tenant_a", "tenant_b", "tenant_c"}


def extract_payload(record):
    envelope = json.loads(record["body"])

    if isinstance(envelope, dict) and "Message" in envelope:
        message = envelope["Message"]
        payload = json.loads(message) if isinstance(message, str) else message
    else:
        payload = envelope

    if not isinstance(payload, dict):
        raise ValueError("Payload inválido")

    if payload.get("eventType") != "candidate.hired":
        raise ValueError("Evento distinto de candidate.hired")

    tenant = str(payload.get("tenantId") or "").strip().lower()
    if tenant not in ALLOWED_TENANTS:
        raise ValueError("Tenant no autorizado")

    candidate_id = str(payload.get("candidateId") or "").strip()
    full_name = str(payload.get("fullName") or "").strip()
    email = str(payload.get("email") or "").strip().lower()

    if not 1 <= len(candidate_id) <= 100:
        raise ValueError("candidateId inválido")

    if not full_name or not email or "@" not in email:
        raise ValueError("Nombre o email inválido")

    names = full_name.split(maxsplit=1)
    first_name = names[0]
    last_name = names[1] if len(names) > 1 else ""

    if len(first_name) > 50 or len(last_name) > 50 or len(email) > 120:
        raise ValueError("Datos exceden los límites de PostgreSQL")

    return tenant, candidate_id, first_name, last_name, email


def process_record(record):
    tenant, candidate_id, first_name, last_name, email = extract_payload(record)

    conn = psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", "5432")),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        connect_timeout=5,
    )

    try:
        with conn:
            with conn.cursor() as cursor:
                insert_query = sql.SQL("""
                    INSERT INTO {}.employees (
                        source_candidate_id,
                        first_name,
                        last_name,
                        email,
                        role,
                        hire_date,
                        status
                    )
                    VALUES (%s, %s, %s, %s, 'EMPLOYEE', NULL, 'PENDING_ONBOARDING')
                    ON CONFLICT DO NOTHING
                    RETURNING employee_id
                """).format(sql.Identifier(tenant))

                cursor.execute(
                    insert_query,
                    (candidate_id, first_name, last_name, email),
                )

                row = cursor.fetchone()
                inserted = row is not None

                if inserted:
                    employee_id = str(row[0])
                else:
                    select_query = sql.SQL("""
                        SELECT employee_id, email
                        FROM {}.employees
                        WHERE source_candidate_id = %s
                    """).format(sql.Identifier(tenant))

                    cursor.execute(select_query, (candidate_id,))
                    existing = cursor.fetchone()

                    if not existing:
                        raise ValueError(
                            "Email existente asociado a otro empleado"
                        )

                    if existing[1].lower() != email:
                        raise ValueError(
                            "El candidato ya existe con otro email"
                        )

                    employee_id = str(existing[0])

        logger.info(
            "candidate.hired integrado | tenant=%s candidateId=%s employeeId=%s inserted=%s",
            tenant,
            candidate_id,
            employee_id,
            inserted,
        )

    finally:
        conn.close()


def lambda_handler(event, context):
    failures = []

    for record in event.get("Records", []):
        try:
            process_record(record)
        except Exception:
            logger.exception(
                "Error procesando candidate.hired | messageId=%s",
                record.get("messageId"),
            )
            failures.append({
                "itemIdentifier": record["messageId"]
            })

    return {"batchItemFailures": failures}
