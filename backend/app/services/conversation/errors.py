"""对话服务的业务错误，统一映射为契约中的错误码。"""

from __future__ import annotations


class ConversationError(Exception):
    """所有对话服务可预期错误的基类。"""

    http_status = 400
    code = "invalid_input"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def payload(self) -> dict:
        return {"error": self.code, "detail": self.message, **self.details}


class InvalidInput(ConversationError):
    http_status = 400
    code = "invalid_input"


class ProfileNotFound(ConversationError):
    http_status = 404
    code = "not_found"


class VersionConflict(ConversationError):
    http_status = 409
    code = "version_conflict"


class DuplicateDate(ConversationError):
    http_status = 409
    code = "duplicate_date"


class UndoConflict(ConversationError):
    http_status = 409
    code = "undo_conflict"


class ValidationFailed(ConversationError):
    """草稿未通过服务端校验：草稿保留，不写库。"""

    http_status = 422
    code = "validation_failed"

    def __init__(self, message: str, *, errors: list[dict], **extra: object) -> None:
        super().__init__(message, details={"errors": errors, **extra})
        self.errors = errors


class InvalidModelOutput(ConversationError):
    http_status = 422
    code = "invalid_model_output"


class Busy(ConversationError):
    http_status = 429
    code = "processing"


class ModelUnavailable(ConversationError):
    http_status = 503
    code = "model_unavailable"


class ModelTimeout(ConversationError):
    http_status = 504
    code = "timeout"
