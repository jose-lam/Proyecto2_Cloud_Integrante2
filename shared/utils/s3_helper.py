import re
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

ALLOWED_TENANTS = {"tenant_a", "tenant_b", "tenant_c"}
SAFE_SEGMENT_REGEX = re.compile(r"^[a-zA-Z0-9_-]+$")

_s3_client = boto3.client(
    "s3",
    config=Config(signature_version="s3v4")
)


def _validate_segment(value: str, field_name: str) -> str:
    """Valida que un segmento de ruta S3 no contenga caracteres peligrosos ni path traversal."""
    if not value or not SAFE_SEGMENT_REGEX.match(str(value)):
        raise ValueError(f"Segmento S3 inválido para '{field_name}': {value}")
    return str(value)


def validate_tenant_prefix(tenant_id: str) -> str:
    """Verifica que el tenant_id pertenezca a la lista blanca autorizada."""
    if not tenant_id or tenant_id not in ALLOWED_TENANTS:
        raise ValueError(f"Tenant no autorizado para operaciones S3: {tenant_id}")
    return tenant_id


def build_contract_s3_key(tenant_id: str, employee_id: str) -> str:
    """
    Construye la clave S3 aislada para contratos laborales:
    {tenant_id}/core-hr/contracts/{employee_id}_contract.pdf
    """
    clean_tenant = validate_tenant_prefix(tenant_id)
    clean_employee = _validate_segment(employee_id, "employee_id")
    return f"{clean_tenant}/core-hr/contracts/{clean_employee}_contract.pdf"


def build_payslip_s3_key(tenant_id: str, period_id: str, employee_id: str) -> str:
    """
    Construye la clave S3 aislada para boletas de pago:
    {tenant_id}/payroll/slips/{period_id}/{employee_id}.pdf
    """
    clean_tenant = validate_tenant_prefix(tenant_id)
    clean_period = _validate_segment(period_id, "period_id")
    clean_employee = _validate_segment(employee_id, "employee_id")
    return f"{clean_tenant}/payroll/slips/{clean_period}/{clean_employee}.pdf"


def upload_pdf_bytes(bucket_name: str, key: str, pdf_bytes: bytes) -> str:
    """
    Sube el contenido binario de un PDF directamente a Amazon S3.
    """
    if not bucket_name:
        raise ValueError("El nombre del bucket S3 es obligatorio.")
    if not pdf_bytes or not isinstance(pdf_bytes, (bytes, bytearray)):
        raise ValueError("El contenido 'pdf_bytes' debe ser binario no vacío.")

    try:
        _s3_client.put_object(
            Bucket=bucket_name,
            Key=key,
            Body=bytes(pdf_bytes),
            ContentType="application/pdf"
        )
        return key
    except ClientError as exc:
        raise RuntimeError(f"Error al subir PDF a S3 ({key}): {exc}") from exc


def generate_upload_presigned_url(bucket_name: str, key: str, expires_in: int = 300) -> str:
    """
    Genera una URL prefirmada (HTTP PUT) para subida directa de PDF desde el cliente.
    """
    if not bucket_name:
        raise ValueError("El nombre del bucket S3 es obligatorio.")

    try:
        return _s3_client.generate_presigned_url(
            ClientMethod="put_object",
            Params={
                "Bucket": bucket_name,
                "Key": key,
                "ContentType": "application/pdf"
            },
            ExpiresIn=int(expires_in)
        )
    except ClientError as exc:
        raise RuntimeError(f"Error al generar URL prefirmada de subida ({key}): {exc}") from exc


def generate_download_presigned_url(bucket_name: str, key: str, expires_in: int = 900) -> str:
    """
    Genera una URL prefirmada (HTTP GET) para descarga segura de un PDF en S3.
    """
    if not bucket_name:
        raise ValueError("El nombre del bucket S3 es obligatorio.")

    try:
        return _s3_client.generate_presigned_url(
            ClientMethod="get_object",
            Params={
                "Bucket": bucket_name,
                "Key": key,
                "ResponseContentType": "application/pdf"
            },
            ExpiresIn=int(expires_in)
        )
    except ClientError as exc:
        raise RuntimeError(f"Error al generar URL prefirmada de descarga ({key}): {exc}") from exc
