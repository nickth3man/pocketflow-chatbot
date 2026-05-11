import re

_RE_SYNTAX_ERROR = re.compile(r"\bsyntax\s*error\b|\bparser\s+error\b", re.IGNORECASE)
_RE_MISSING_COLUMN = re.compile(
    r"\bcolumn\b.*\b(not found|does not exist|not exist)\b", re.IGNORECASE
)
_RE_MISSING_TABLE = re.compile(
    r"\btable\b.*\b(not found|does not exist|not exist)\b", re.IGNORECASE
)
_RE_TYPE_MISMATCH = re.compile(
    r"\b(type mismatch|cannot be cast|conversion failed|invalid type)\b",
    re.IGNORECASE,
)
_RE_PERMISSION = re.compile(
    r"\b(permission|not authorized|not allowed|access denied)\b", re.IGNORECASE
)


def classify_error(error_message: str) -> str:
    if not error_message:
        return "unknown"

    msg_lower = error_message.lower()

    if _RE_SYNTAX_ERROR.search(msg_lower):
        return "syntax_error"

    if _RE_MISSING_COLUMN.search(msg_lower):
        return "missing_column"

    if _RE_MISSING_TABLE.search(msg_lower):
        return "missing_table"

    if _RE_TYPE_MISMATCH.search(msg_lower):
        return "type_mismatch"

    if _RE_PERMISSION.search(msg_lower):
        return "permission"

    return "unknown"
