class VogiError(Exception):
    """Base application exception."""


class ToolExecutionError(VogiError):
    """Raised when an agent tool cannot be executed."""


class ModelProviderError(VogiError):
    """Raised when a model provider request fails."""


class ValidationError(VogiError):
    """Raised when an API or tool payload is invalid."""

