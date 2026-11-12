import os
import uuid
from shared.middlewares.db_tenant_middleware import with_tenant_db
from shared.utils.response import success, error
from shared.utils.s3_helper import generate_download_presigned_url

S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME", "[FALTA_INTEGRANTE_1_NOMBRE_BUCKET_S3]")


@with_tenant_db
def lambda_handler(event, context, conn, cursor, tenant_id, role, auth_employee_id):
    """
    GET /employees/{id}/contract-url
    Genera una URL firmada GET (expiración 900s) para descargar el contrato PDF desde S3.
    """
    path_params = event.get("pathParameters") or {}
    target_employee_id = path_params.get("id")

    if not target_employee_id:
        return error(400, "El parámetro de ruta 'id' del empleado es obligatorio")

    try:
        uuid.UUID(str(target_employee_id))
    except ValueError:
        return error(400, "El formato de 'employee_id' debe ser un UUID válido")

    # Control de acceso RBAC: un EMPLOYEE solo puede descargar su propio contrato
    if role == "EMPLOYEE" and str(auth_employee_id) != str(target_employee_id):
        return error(403, "No tiene permisos para descargar el contrato de otro empleado")

    cursor.execute(
        """
        SELECT
            c.contract_id,
            c.employee_id,
            c.contract_type,
            c.start_date,
            c.s3_contract_key,
            e.first_name,
            e.last_name
        FROM contracts c
        INNER JOIN employees e ON c.employee_id = e.employee_id
        WHERE c.employee_id = %s
        ORDER BY c.start_date DESC
        LIMIT 1;
        """,
        (str(target_employee_id),)
    )
    contract = cursor.fetchone()

    if not contract:
        return error(404, "Contrato no encontrado para el empleado especificado")

    s3_key = contract.get("s3_contract_key")
    if not s3_key:
        return error(404, "El contrato aún no tiene un documento PDF almacenado en S3")

    # Verificación adicional de aislamiento multi-tenant sobre la ruta almacenada
    expected_prefix = f"{tenant_id}/core-hr/contracts/"
    if not s3_key.startswith(expected_prefix):
        return error(403, "Violación de aislamiento de ruta multi-tenant detectada")

    download_url = generate_download_presigned_url(
        bucket_name=S3_BUCKET_NAME,
        key=s3_key,
        expires_in=900
    )

    return success(200, {
        "downloadUrl": download_url,
        "s3Key": s3_key,
        "expiresIn": 900,
        "employeeId": str(target_employee_id),
        "employeeName": f"{contract['first_name']} {contract['last_name']}",
        "contractId": str(contract["contract_id"])
    })
