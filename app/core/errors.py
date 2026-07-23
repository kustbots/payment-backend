class AppError(Exception):
    """Base class for domain errors that routers translate into HTTP responses."""

    status_code = 400

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class InsufficientPointsError(AppError):
    status_code = 402

    def __init__(self, balance: float | None = None, required: float | None = None):
        self.balance = balance
        self.required = required
        msg = "Insufficient points balance"
        if balance is not None and required is not None:
            msg = f"Insufficient points balance: have {balance}, need {required}"
        super().__init__(msg)


class UserNotFoundError(AppError):
    status_code = 404

    def __init__(self):
        super().__init__("User not found")


class NotFoundError(AppError):
    status_code = 404


class ConflictError(AppError):
    status_code = 409


class ValidationAppError(AppError):
    status_code = 422


class AuthError(AppError):
    status_code = 401


class UpstreamServiceError(AppError):
    status_code = 502
