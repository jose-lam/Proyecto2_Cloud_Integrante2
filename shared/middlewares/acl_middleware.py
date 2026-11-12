import functools
from typing import Iterable, Optional
from shared.utils.response import error

PRIVILEGED_ADMIN_ROLES = {"ADMIN", "HR_MANAGER"}


def _extract_role(event: dict) -> str:
    """Extrae y normaliza el rol desde el Custom Authorizer de API Gateway."""
    authorizer = (event or {}).get("requestContext", {}).get("authorizer") or {}
    return str(authorizer.get("role") or "").strip().upper()


def require_roles(allowed_roles: Iterable[str]):
    """
    Decorador ACL basado en roles (RBAC) para funciones AWS Lambda.
    Verifica `event['requestContext']['authorizer']['role']` contra `allowed_roles`.
    Si el rol no está autorizado, retorna HTTP 403 Forbidden sin abrir conexión a RDS.
    """
    normalized_allowed = {str(r).strip().upper() for r in allowed_roles if r}

    def decorator(func):
        @functools.wraps(func)
        def wrapper(event, context, *args, **kwargs):
            role = _extract_role(event)

            if not role:
                return error(
                    401,
                    "No autorizado: el token no contiene un rol válido en el autorizador"
                )

            if role not in normalized_allowed:
                return error(
                    403,
                    f"Acceso denegado (Forbidden): el rol '{role}' no tiene permisos para este recurso",
                    details={
                        "currentRole": role,
                        "allowedRoles": sorted(normalized_allowed)
                    }
                )

            return func(event, context, *args, **kwargs)

        return wrapper

    return decorator


def enforce_self_or_admin(
    role: str,
    auth_employee_id: Optional[str],
    target_employee_id: Optional[str]
) -> Optional[dict]:
    """
    Garantiza aislamiento horizontal a nivel de usuario:
    - 'ADMIN' y 'HR_MANAGER' pueden operar sobre cualquier employee_id del tenant.
    - 'EMPLOYEE' únicamente puede acceder o modificar su propio employee_id.

    Retorna None si el acceso es válido, o una respuesta HTTP 403 Forbidden si es denegado.
    """
    normalized_role = str(role or "").strip().upper()

    if normalized_role in PRIVILEGED_ADMIN_ROLES:
        return None

    if normalized_role == "EMPLOYEE":
        auth_id = str(auth_employee_id or "").strip()
        target_id = str(target_employee_id or "").strip()

        if not auth_id or not target_id or auth_id != target_id:
            return error(
                403,
                "Acceso denegado (Forbidden): un usuario con rol EMPLOYEE solo puede acceder a sus propios recursos"
            )
        return None

    return error(
        403,
        f"Acceso denegado (Forbidden): rol '{normalized_role}' no autorizado para esta operación"
    )
