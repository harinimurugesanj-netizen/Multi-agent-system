"""Application errors. Each carries a stable `code` (stored in graph state) and a message
that is safe to show to a customer (no SQL, no internals)."""


class AppError(Exception):
    code = "internal_error"
    safe_message = "Sorry, something went wrong on our side. Please try again."

    def __init__(self, detail: str = "", **context):
        super().__init__(detail or self.code)
        self.detail = detail
        self.context = context


class DatabaseUnavailable(AppError):
    code = "db_unavailable"
    safe_message = "We can't reach our pricing system right now. Please try again in a few minutes."


class PricingNotFound(AppError):
    code = "pricing_not_found"
    safe_message = "Sorry, we don't have a price for that combination yet, so I can't prepare a quotation."


class QuotationNotFound(AppError):
    code = "quotation_not_found"
    safe_message = "I couldn't find a matching previous quotation on your account."


class UnauthorizedAccess(AppError):
    code = "unauthorized"
    safe_message = "I can't access that information for your account."


class PersistenceError(AppError):
    code = "persistence_failed"
    safe_message = "Your quotation could not be saved, so it has not been recorded. Please try again."


class LLMUnavailable(AppError):
    code = "llm_unavailable"
    safe_message = "Our assistant is temporarily unavailable. Please try again shortly."


# code -> message shown to customers (also covers codes that are not exceptions)
ERROR_MESSAGES: dict[str, str] = {
    cls.code: cls.safe_message
    for cls in (DatabaseUnavailable, PricingNotFound, QuotationNotFound,
                UnauthorizedAccess, PersistenceError, LLMUnavailable)
}
ERROR_MESSAGES.update({
    "invalid_estimation": "Sorry, I couldn't produce a reliable estimate for that, so nothing was saved. Please try again or contact us.",
    "no_change": "That matches your existing quotation exactly, so I haven't created a new one. Tell me what you would like to change.",
    "too_many_clarifications": "I'm having trouble understanding the details. Please describe the frame you want (size, material and glass type) in a new message.",
})


def safe_message_for(code: str | None) -> str:
    return ERROR_MESSAGES.get(code or "", AppError.safe_message)
