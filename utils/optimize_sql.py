import re

_RE_LIMIT_CLAUSE = re.compile(
    r"\bLIMIT\s+\d+(\s*OFFSET\s+\d+)?\s*;?\s*$",
    re.IGNORECASE,
)


def optimize_sql(sql: str, default_limit: int = 200) -> str:
    sql = sql.strip()

    has_limit = _RE_LIMIT_CLAUSE.search(sql)
    if not has_limit:
        sql = sql.rstrip(";").strip() + f" LIMIT {default_limit}"

    if not sql.endswith(";"):
        sql += ";"

    return sql
