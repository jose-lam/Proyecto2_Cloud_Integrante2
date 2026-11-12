import sys
import os

for rel_path in ("../", "../../../"):
    abs_path = os.path.abspath(os.path.join(os.path.dirname(__file__), rel_path))
    if abs_path not in sys.path:
        sys.path.append(abs_path)

from shared.middlewares.acl_middleware import require_roles
from shared.middlewares.db_tenant_middleware import with_tenant_db
from shared.utils.response import success, error
from shared.utils.s3_helper import build_contract_s3_key, generate_upload_presigned_url

S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME", "[FALTA_INTEGRANTE_1_NOMBRE_BUCKET_S3]")
PRESIGNED_EXPIRATION_SECONDS = int(os.environ.get("PRESIGNED_EXPIRATION_SECONDS", "300"))


@require_roles(allowed_roles=["ADMIN", "HR_MANAGER"])
@with_tenant_db
def lambda_handler(event, context, conn, cursor, tenant_id, role, auth_employee_id):
    path_params = event.get("pathParameters") or {}
    target_employee_id = path_params.get("employee_id") or path_params.get("id")

    if not target_employee_id:
        return error(400, "El parámetro 'employee_id' en la ruta es obligatorio")

    if not S3_BUCKET_NAME or S3_BUCKET_NAME.startswith("[FALTA_"):
        return error(500, "Variable de entorno S3_BUCKET_NAME no configurada")

    # Verificar que el empleado existe dentro del esquema aislado del tenant
    cursor.execute(
        """
        SELECT employee_id, first_name, last_name
        FROM employees
        WHERE employee_id = %s;
        """,
        (target_employee_id,)
    )
    employee_row = cursor.fetchone()
    if not employee_row:
        return error(404, f"Empleado '{target_employee_id}' no encontrado en el tenant '{tenant_id}'")

    try:
        s3_key = build_contract_s3_key(tenant_id, str(target_employee_id))
        upload_url = generate_upload_presigned_url(
            bucket_name=S3_BUCKET_NAME,
            key=s3_key,
            expires_in=PRESIGNED_EXPIRATION_SECONDS
        )
    except ValueError as val_err:
        return error(400, str(val_err))
    except RuntimeError as s3_err:
        return error(500, "No se pudo generar la URL prefirmada de S3", details=str(s3_err))

    return success(200, {
        "tenantId": tenant_id,
        "employeeId": str(target_employee_id),
        "s3Key": s3_key,
        "uploadUrl": upload_url,
        "expiresInSeconds": PRESIGNED_EXPIRATION_SECONDS,
        "requiredHeaders": {
            "Content-Type": "application/pdf"
        }
    })
