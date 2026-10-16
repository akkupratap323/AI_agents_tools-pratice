"""
errors.py - ToolError, the ONE way a tool reports an expected failure.

Expected failures (not found, bad input, not allowed in this state) are RAISED
as ToolError and rendered to JSON by the dispatcher. Why raise instead of
returning an error dict from the handler?
  - handlers stay linear: guard clauses first, happy path last
  - one place (the dispatcher) owns the error JSON shape
  - a forgotten `return` can't silently turn an error into a success

Every ToolError carries:
  code     stable machine-readable id, e.g. "order_not_found"
  message  human-readable, includes the offending value
  hint     what the model should do next (the key to self-recovery)
  extra    structured context, e.g. the valid options
"""


class ToolError(Exception):
    def __init__(self, code, message, hint=None, **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.extra = extra

    def to_dict(self):
        out = {"error": self.code, "message": self.message}
        if self.hint:
            out["hint"] = self.hint
        out.update(self.extra)
        return out
