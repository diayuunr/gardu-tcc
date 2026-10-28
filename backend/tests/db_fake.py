"""Fake Supabase generik di memori untuk test Fase E: tabel berisi baris dict, query builder bergaya PostgREST
(select/insert/update/delete + eq/neq/in_/lt/is_/order/range/limit) dan `auth.get_user`."""

import itertools
import uuid
from datetime import datetime, timezone

from supabase_auth.errors import AuthApiError


class Resp:
    def __init__(self, data, count=None):
        self.data, self.count = data, count


class Query:
    def __init__(self, table, op, payload=None, columns=None, want_count=False):
        self.table, self.op, self.payload, self.columns, self.want_count = table, op, payload, columns, want_count
        self.filters: list = []
        self._order: tuple[str, bool] | None = None
        self._range: tuple[int, int] | None = None
        self._limit: int | None = None

    # ---- filter
    def eq(self, key, value):
        self.filters.append(lambda row: row.get(key) == value)
        return self

    def neq(self, key, value):
        self.filters.append(lambda row: row.get(key) != value)
        return self

    def in_(self, key, values):
        self.filters.append(lambda row: row.get(key) in values)
        return self

    def lt(self, key, value):
        self.filters.append(lambda row: row.get(key) is not None and str(row.get(key)) < str(value))
        return self

    def is_(self, key, value):
        self.filters.append(lambda row: (row.get(key) is None) == (value == "null"))
        return self

    def like(self, key, pattern):
        prefix = pattern.rstrip("%")
        self.filters.append(lambda row: str(row.get(key) or "").startswith(prefix))
        return self

    def or_(self, expression):
        """Hanya klausa `kolom.is.null` / `kolom.eq.nilai` (cukup untuk query job reprocess dan skor)."""
        clauses = []
        for part in expression.split(","):
            column, op, value = part.split(".", 2)
            clauses.append((column, op, value))

        def matches(row):
            for column, op, value in clauses:
                if op == "is" and value == "null" and row.get(column) is None:
                    return True
                if op == "eq" and str(row.get(column)).casefold() == value.casefold():
                    return True
            return False

        self.filters.append(matches)
        return self

    def order(self, column, desc=False):
        self._order = (column, desc)
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def limit(self, n):
        self._limit = n
        return self

    # ---- eksekusi
    def _matching(self):
        return [row for row in self.table.rows if all(f(row) for f in self.filters)]

    def execute(self):
        logged = dict(self.payload) if isinstance(self.payload, dict) else None
        if self.op == "select":
            logged = {"columns": self.columns}  # test privasi memeriksa kolom apa saja yang diminta
        self.table.db.log.append((self.table.name, self.op, logged))
        if self.table.db.fail_on.get((self.table.name, self.op)):
            raise RuntimeError("database mati (simulasi)")
        if self.op == "insert":
            created = []
            for payload in self.payload if isinstance(self.payload, list) else [self.payload]:
                row = {"id": str(uuid.uuid4()), "created_at": datetime.now(timezone.utc).isoformat(), **self.table.defaults, **payload}
                if self.table.numbered:
                    row["public_number"] = next(self.table.db.counter)
                self.table.rows.append(row)
                created.append(dict(row))
            return Resp(created)
        if self.op == "update":
            rows = self._matching()
            for row in rows:
                row.update(self.payload)
            return Resp([dict(r) for r in rows])
        if self.op == "delete":
            rows = self._matching()
            self.table.rows[:] = [r for r in self.table.rows if r not in rows]
            return Resp([dict(r) for r in rows])
        rows = self._matching()
        total = len(rows)
        if self._order:
            column, desc = self._order
            rows.sort(key=lambda r: (r.get(column) is None, r.get(column)), reverse=desc)
        if self._range:
            rows = rows[self._range[0] : self._range[1] + 1]
        if self._limit is not None:
            rows = rows[: self._limit]
        columns = [c.strip() for c in self.columns.split(",")] if self.columns and self.columns != "*" else None
        data = [{c: row.get(c) for c in columns} if columns else dict(row) for row in rows]
        return Resp(data, count=total if self.want_count else None)


class Table:
    def __init__(self, db, name, rows, defaults=None, numbered=False):
        self.db, self.name, self.rows, self.defaults, self.numbered = db, name, rows, defaults or {}, numbered

    def select(self, columns="*", count=None):
        return Query(self, "select", columns=columns, want_count=count == "exact")

    def insert(self, payload):
        return Query(self, "insert", payload)

    def update(self, payload):
        return Query(self, "update", payload)

    def delete(self):
        return Query(self, "delete")


class FakeAuth:
    def __init__(self, tokens: dict[str, str], down: bool = False):
        self.tokens, self.down = tokens, down

    def get_user(self, token):
        if self.down:
            import httpx

            raise httpx.ConnectError("auth mati (simulasi)")
        if token not in self.tokens:
            raise AuthApiError("invalid JWT", 401, "bad_jwt")

        class _User:
            id = self.tokens[token]

        class _Response:
            user = _User()

        return _Response()


class FakeDb:
    """`FakeDb(reports=[...], incidents=[...], moderators=[...], tokens={"jwt": "user-id"})`."""

    def __init__(self, reports=None, incidents=None, moderators=None, areas=None, tokens=None):
        self.log: list = []
        self.fail_on: dict = {}
        self.counter = itertools.count(1000)
        self.tables = {
            "reports": Table(self, "reports", reports if reports is not None else [], {"status": "menunggu_verifikasi"}, numbered=True),
            "incidents": Table(self, "incidents", incidents if incidents is not None else [], {"status": "baru", "is_seed_data": False}),
            "moderators": Table(self, "moderators", moderators if moderators is not None else []),
            "areas": Table(self, "areas", areas if areas is not None else []),
            "risk_scores": Table(self, "risk_scores", []),
        }
        self.auth = FakeAuth(tokens or {})

    def table(self, name):
        return self.tables[name]

    def rows(self, name):
        return self.tables[name].rows

    def row(self, name, row_id):
        return next(r for r in self.tables[name].rows if r["id"] == row_id)

    def writes(self, name=None):
        return [entry for entry in self.log if entry[1] in {"insert", "update", "delete"} and (name is None or entry[0] == name)]
