import re


def validate_sql_safety(sql: str) -> tuple[bool, str]:
    stripped = sql.strip()

    if not stripped:
        return False, "SQL statement is empty"

    if not stripped.upper().startswith("SELECT"):
        return False, "Only SELECT statements are allowed"

    dangerous = re.findall(
        r"\b(CREATE|DROP|ALTER|INSERT|UPDATE|DELETE|TRUNCATE|REPLACE|"
        r"GRANT|REVOKE|EXEC|EXECUTE|LOAD|IMPORT|ATTACH|DETACH)\b",
        stripped,
        re.IGNORECASE,
    )
    if dangerous:
        unique = list(dict.fromkeys(dangerous))
        return (
            False,
            f"DDL/DML keywords not allowed: {', '.join(unique)}",
        )

    return True, "SQL is safe"
