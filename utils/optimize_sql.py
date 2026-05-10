import re


def optimize_sql(sql: str, default_limit: int = 200) -> str:
    sql = sql.strip()

    has_limit = re.search(
        r"\bLIMIT\s+\d+(\s*OFFSET\s+\d+)?\s*$",
        sql,
        re.IGNORECASE,
    )
    if not has_limit:
        sql = sql.rstrip(";").strip() + f" LIMIT {default_limit}"

    if not sql.endswith(";"):
        sql += ";"

    return sql
