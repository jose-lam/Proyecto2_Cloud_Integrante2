import json
from handlers import (
    calculate_payroll,
    get_payrolls_by_period,
    get_employee_pay_slips,
)

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
}

ROUTES = {
    ("POST", "/payrolls/calculate"): calculate_payroll.lambda_handler,
    ("GET", "/payrolls/{period}"): get_payrolls_by_period.lambda_handler,
    ("GET", "/payrolls/employee/{employee_id}"): get_employee_pay_slips.lambda_handler,
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
