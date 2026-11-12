import json
from handlers import (
    get_departments,
    create_department,
    get_employees,
    get_employee_by_id,
    create_employee,
    update_employee,
    get_contract_upload_url,
    get_contract_download_url,
)

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
}

ROUTES = {
    ("GET", "/departments"): get_departments.lambda_handler,
    ("POST", "/departments"): create_department.lambda_handler,
    ("GET", "/employees"): get_employees.lambda_handler,
    ("GET", "/employees/{id}"): get_employee_by_id.lambda_handler,
    ("POST", "/employees"): create_employee.lambda_handler,
    ("PUT", "/employees/{id}"): update_employee.lambda_handler,
    ("POST", "/employees/{id}/contract-upload-url"): get_contract_upload_url.lambda_handler,
    ("GET", "/employees/{id}/contract-url"): get_contract_download_url.lambda_handler,
}


def lambda_handler(event, context):
    method = event.get("httpMethod", "").upper()
    resource = event.get("resource", "")

    if method == "OPTIONS":
        return {"statusCode": 200, "headers": CORS_HEADERS, "body": ""}

    handler = ROUTES.get((method, resource))
    if not handler:
        return {
            "statusCode": 404,
            "headers": CORS_HEADERS,
            "body": json.dumps({"message": f"Ruta no encontrada: {method} {resource}"}),
        }

    return handler(event, context)
