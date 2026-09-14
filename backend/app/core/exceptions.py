"""Domain exceptions.

Services raise these; the API layer is the only place that knows how to turn
them into HTTP status codes. Nothing here imports FastAPI.
"""


class AppError(Exception):
    """Base for every error this application raises deliberately."""

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.__class__.__name__


class ConfigurationError(AppError):
    """Missing or invalid configuration. Raised at startup, never mid-call."""


# --- Provider errors -------------------------------------------------------


class ProviderError(AppError):
    """An upstream AI or telephony vendor failed."""

    def __init__(self, provider: str, message: str, *, status_code: int | None = None) -> None:
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.status_code = status_code


class TranslationFailedError(ProviderError):
    pass


class SpeechToTextFailedError(ProviderError):
    pass


class TextToSpeechFailedError(ProviderError):
    pass


class UnsupportedLanguagePairError(AppError):
    """The configured translator cannot serve this source/target pair."""


# --- Call / pairing errors -------------------------------------------------


class RoomNotFoundError(AppError):
    """Room code does not exist, already paired, or expired."""


class RoomCodeExhaustedError(AppError):
    """Could not allocate a free room code after the configured retries."""


class InvalidStateTransitionError(AppError):
    """The IVR was asked to do something illegal from its current state."""


class LegNotFoundError(AppError):
    pass
