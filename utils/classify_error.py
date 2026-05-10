import re


def classify_error(error_message: str) -> str:
    if not error_message:
        return "unknown"

    msg_lower = error_message.lower()

    if re.search(r"\bsyntax\s*error\b|\bparser\s+error\b", msg_lower):
        return "syntax_error"

    if re.search(r"\bcolumn\b.*\b(not found|does not exist|not exist)\b", msg_lower):
        return "missing_column"

    if re.search(r"\btable\b.*\b(not found|does not exist|not exist)\b", msg_lower):
        return "missing_table"

    if re.search(
        r"\b(type mismatch|cannot be cast|conversion failed|invalid type)\b",
        msg_lower,
    ):
        return "type_mismatch"

    if re.search(
        r"\b(permission|not authorized|not allowed|access denied)\b", msg_lower
    ):
        return "permission"

    return "unknown"
