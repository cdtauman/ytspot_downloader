"""
error_handler_patch.py  –  Add 'retriable' field to ErrorInfo
==============================================================
Apply these changes to error_handler.py:

1. Add the `retriable` field to the ErrorInfo dataclass.
2. Update classify_error() to set it.
3. Update _match_patterns() to call is_retriable().

CHANGE 1: Update the ErrorInfo dataclass
─────────────────────────────────────────

    @dataclass
    class ErrorInfo:
        severity:   ErrorSeverity
        headline:   str
        detail:     str
        raw:        str  = ""
        retriable:  bool = False   # ← ADD THIS FIELD

        def is_fatal(self) -> bool:
            return self.severity == ErrorSeverity.CRITICAL

        def status_line(self) -> str:
            ...


CHANGE 2: Add import at top of error_handler.py
────────────────────────────────────────────────

    from core.retry_policy import is_retriable as _is_retriable


CHANGE 3: Update _match_patterns() return — add retriable flag
──────────────────────────────────────────────────────────────

Replace the existing _match_patterns function body's return statements:

OLD:
    return ErrorInfo(
        severity=severity,
        headline=headline,
        detail=detail,
        raw=raw_msg,
    )

NEW:
    return ErrorInfo(
        severity=severity,
        headline=headline,
        detail=detail,
        raw=raw_msg,
        retriable=_is_retriable(raw_msg),
    )

And for the generic fallback at the end of _match_patterns:

OLD:
    return ErrorInfo(
        severity=default_severity,
        headline="Download failed",
        detail=f"An unexpected error occurred:\\n\\n{short}...",
        raw=raw_msg,
    )

NEW:
    return ErrorInfo(
        severity=default_severity,
        headline="Download failed",
        detail=f"An unexpected error occurred:\\n\\n{short}...",
        raw=raw_msg,
        retriable=_is_retriable(raw_msg),
    )
"""
