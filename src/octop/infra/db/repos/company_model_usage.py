"""Model-service metering without inventing execution agents at the identity center."""

from __future__ import annotations

from typing import Any

from octop.infra.db.pool import DatabasePool
from octop.infra.db.repos._base import insert_returning_id, now_ts


class CompanyModelUsageRepo:
    def __init__(self, db: DatabasePool) -> None:
        self.db = db

    def record(
        self,
        *,
        user_id: int,
        model: str,
        request_id: str,
        input_tokens: int,
        output_tokens: int,
        source: str,
    ) -> int:
        with self.db.transaction() as conn:
            return insert_returning_id(
                conn,
                "INSERT INTO company_model_usage(request_id,ts,user_id,model,input_tokens,output_tokens,total_tokens,source) VALUES(?,?,?,?,?,?,?,?)",
                (
                    request_id,
                    now_ts(),
                    user_id,
                    model,
                    input_tokens,
                    output_tokens,
                    input_tokens + output_tokens,
                    source,
                ),
            )

    def total_tokens_for_user(self, user_id: int) -> int:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(total_tokens),0) AS total FROM company_model_usage WHERE user_id=?",
                (user_id,),
            ).fetchone()
        return int(row["total"] if row else 0)

    def summary(self) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT user_id,COUNT(*) AS requests,SUM(input_tokens) AS input_tokens,SUM(output_tokens) AS output_tokens,SUM(total_tokens) AS total_tokens FROM company_model_usage GROUP BY user_id ORDER BY user_id"
            ).fetchall()
        return [dict(row) for row in rows]

    def window(self, since: int, until: int, user_id: int | None) -> list[dict[str, Any]]:
        condition = "ts>=? AND ts<?"
        args: list[Any] = [since, until]
        if user_id is not None:
            condition += " AND user_id=?"
            args.append(user_id)
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT user_id,model,COUNT(*) AS requests,SUM(input_tokens) AS input_tokens,"
                "SUM(output_tokens) AS output_tokens,SUM(total_tokens) AS total_tokens,"
                "SUM(CASE WHEN source='dora_model_estimate' THEN 1 ELSE 0 END) AS estimated_requests,"
                "MAX(ts) AS last_used FROM company_model_usage WHERE "
                + condition
                + " GROUP BY user_id,model ORDER BY SUM(total_tokens) DESC,user_id,model",
                args,
            ).fetchall()
        return [dict(row) for row in rows]
