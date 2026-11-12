import json

def success(status_code: int, body: any) -> dict:
    """
    Genera una respuesta HTTP exitosa con formato API Gateway Proxy Integration.
    """
    return {
        "statusCode": status_code,
        "headers": {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS"
        },
        "body": json.dumps(body, default=str)
    }

def error(status_code: int, message: str, details: any = None) -> dict:
    """
    Genera una respuesta HTTP de error con formato API Gateway Proxy Integration.
    """
    payload = {"message": message}
    if details is not None:
        payload["details"] = details

    return {
        "statusCode": status_code,
        "headers": {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS"
        },
        "body": json.dumps(payload, default=str)
    }
