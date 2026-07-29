from typing import Any, Dict, Optional


class AppException(Exception):
    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class ValidationError(AppException):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__("VALIDATION_ERROR", message, details)


class NotFoundError(AppException):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__("NOT_FOUND", message, details)


class ServiceError(AppException):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__("SERVICE_ERROR", message, details)


class AuthError(AppException):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__("AUTH_ERROR", message, details)


class RateLimitError(AppException):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__("RATE_LIMIT", message, details)


ERROR_CODES = {
    "VALIDATION_ERROR": {"status_code": 400, "category": "validation"},
    "NOT_FOUND": {"status_code": 404, "category": "resource"},
    "AUTH_ERROR": {"status_code": 401, "category": "authentication"},
    "RATE_LIMIT": {"status_code": 429, "category": "rate_limit"},
    "SERVICE_ERROR": {"status_code": 500, "category": "service"},
}


def get_error_info(code: str) -> Dict[str, Any]:
    return ERROR_CODES.get(code, {"status_code": 500, "category": "unknown"})


def handle_exception(e: Exception) -> Dict[str, Any]:
    if isinstance(e, AppException):
        error_info = get_error_info(e.code)
        return {
            "code": e.code,
            "message": e.message,
            "details": e.details,
            "status_code": error_info["status_code"],
            "category": error_info["category"],
        }

    return {
        "code": "INTERNAL_ERROR",
        "message": "服务器内部错误",
        "details": {"error": str(e)},
        "status_code": 500,
        "category": "internal",
    }
