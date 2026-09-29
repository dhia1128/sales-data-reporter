class AppError(Exception):
    """Base class for errors that should be shown to the user."""

    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class InvalidUpload(AppError):
    status_code = 400


class UnprocessableData(AppError):
    status_code = 422


class NotFound(AppError):
    status_code = 404
