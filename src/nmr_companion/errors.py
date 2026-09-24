class NmrError(ValueError):
    """A bounded, actionable domain failure."""

    def __init__(self, code: str, message: str, *, current_revision: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.current_revision = current_revision
