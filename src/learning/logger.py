"""
Interaction logger: captures (query → params → outcome) tuples to JSONL + SQLite.

Storage location: ~/.logistics_agent/
  - interactions.jsonl  — append-only primary write path
  - interactions.db     — SQLite query layer, rebuilt from JSONL at startup

All public methods catch-and-swallow all exceptions so the app never fails
due to logging errors.
"""
import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parents[2] / "data"
JSONL_PATH = DATA_DIR / "interactions.jsonl"
DB_PATH = DATA_DIR / "interactions.db"

SCHEMA_VERSION = 1


class InteractionLogger:
    def __init__(self) -> None:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            self._ensure_db()
        except Exception:
            pass

    def new_session(self) -> str:
        """Create and return a new session UUID."""
        return str(uuid.uuid4())

    def log_interaction(
        self,
        session_id: str,
        turn_index: int,
        query_text: str,
        inferred_params: dict,
        solver_calls: list,
        agent_turn_count: int,
    ) -> str:
        """Append one interaction record to JSONL. Returns event_id."""
        event_id = str(uuid.uuid4())
        try:
            record = {
                "schema_version": SCHEMA_VERSION,
                "event_id": event_id,
                "session_id": session_id,
                "session_timestamp": datetime.now().isoformat(timespec="seconds"),
                "turn_index": turn_index,
                "query_text": query_text,
                "inferred_params": inferred_params,
                "solver_calls": solver_calls,
                "solver_call_count": len(solver_calls),
                "agent_turn_count": agent_turn_count,
            }
            with JSONL_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception:
            pass
        return event_id

    def log_session_rating(
        self,
        session_id: str,
        rating: int,
        total_queries: int,
        total_solver_calls: int,
    ) -> None:
        """Append a session_rating event to JSONL."""
        try:
            record = {
                "event_type": "session_rating",
                "session_id": session_id,
                "rating": rating,
                "total_queries": total_queries,
                "total_solver_calls": total_solver_calls,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
            }
            with JSONL_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception:
            pass

    def get_few_shot_examples(self, limit: int = 5, min_rating: int = 2) -> list[dict]:
        """Return up to `limit` (query_text, params) pairs from rated sessions."""
        try:
            self._sync_jsonl_to_db()
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute(
                """
                SELECT i.query_text, i.inferred_params_json
                FROM interactions i
                JOIN session_ratings sr ON i.session_id = sr.session_id
                WHERE sr.rating >= ? AND i.inferred_params_json != '{}'
                ORDER BY i.session_timestamp DESC
                LIMIT ?
                """,
                (min_rating, limit),
            )
            rows = cur.fetchall()
            conn.close()
            examples = []
            for query_text, params_json in rows:
                try:
                    params = json.loads(params_json)
                    examples.append({"query_text": query_text, "params": params})
                except Exception:
                    pass
            return examples
        except Exception:
            return []

    def get_popular_constraint_patterns(self) -> dict:
        """Return counts of how often each objective has been used."""
        try:
            self._sync_jsonl_to_db()
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("SELECT inferred_params_json FROM interactions")
            rows = cur.fetchall()
            conn.close()
            objectives: dict[str, int] = {}
            for (params_json,) in rows:
                try:
                    params = json.loads(params_json)
                    obj = params.get("objective")
                    if obj:
                        objectives[obj] = objectives.get(obj, 0) + 1
                except Exception:
                    pass
            return {"objective_counts": objectives}
        except Exception:
            return {}

    def get_infeasibility_patterns(self) -> list[dict]:
        """Return params dicts for interactions that produced infeasible results."""
        try:
            self._sync_jsonl_to_db()
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute(
                "SELECT inferred_params_json FROM interactions WHERE has_infeasible = 1"
            )
            rows = cur.fetchall()
            conn.close()
            patterns = []
            for (params_json,) in rows:
                try:
                    params = json.loads(params_json)
                    patterns.append(params)
                except Exception:
                    pass
            return patterns
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _sync_jsonl_to_db(self) -> None:
        """Incrementally sync new JSONL records into SQLite (skip known event_ids)."""
        try:
            if not JSONL_PATH.exists():
                return
            self._ensure_db()
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()

            cur.execute("SELECT event_id FROM interactions")
            existing_events = {row[0] for row in cur.fetchall()}

            cur.execute("SELECT session_id FROM session_ratings")
            existing_ratings = {row[0] for row in cur.fetchall()}

            with JSONL_PATH.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except Exception:
                        continue  # skip corrupted lines

                    if record.get("event_type") == "session_rating":
                        sid = record.get("session_id")
                        if sid and sid not in existing_ratings:
                            cur.execute(
                                """INSERT INTO session_ratings
                                   (session_id, rating, total_queries, total_solver_calls, timestamp)
                                   VALUES (?, ?, ?, ?, ?)""",
                                (
                                    sid,
                                    record.get("rating"),
                                    record.get("total_queries", 0),
                                    record.get("total_solver_calls", 0),
                                    record.get("timestamp"),
                                ),
                            )
                            existing_ratings.add(sid)

                    elif record.get("schema_version") == SCHEMA_VERSION:
                        event_id = record.get("event_id")
                        if event_id and event_id not in existing_events:
                            solver_calls = record.get("solver_calls", [])
                            has_infeasible = int(
                                any(c.get("is_feasible") == False for c in solver_calls)  # noqa: E712
                            )
                            cur.execute(
                                """INSERT INTO interactions
                                   (event_id, session_id, session_timestamp, turn_index,
                                    query_text, inferred_params_json, solver_calls_json,
                                    solver_call_count, agent_turn_count, has_infeasible)
                                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                (
                                    event_id,
                                    record.get("session_id"),
                                    record.get("session_timestamp"),
                                    record.get("turn_index", 0),
                                    record.get("query_text", ""),
                                    json.dumps(record.get("inferred_params", {})),
                                    json.dumps(solver_calls),
                                    record.get("solver_call_count", 0),
                                    record.get("agent_turn_count", 0),
                                    has_infeasible,
                                ),
                            )
                            existing_events.add(event_id)

            conn.commit()
            conn.close()
        except Exception:
            pass

    def _ensure_db(self) -> None:
        """Create SQLite tables if they do not exist."""
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS interactions (
                event_id            TEXT PRIMARY KEY,
                session_id          TEXT,
                session_timestamp   TEXT,
                turn_index          INTEGER,
                query_text          TEXT,
                inferred_params_json TEXT,
                solver_calls_json   TEXT,
                solver_call_count   INTEGER,
                agent_turn_count    INTEGER,
                has_infeasible      INTEGER DEFAULT 0
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS session_ratings (
                session_id          TEXT PRIMARY KEY,
                rating              INTEGER,
                total_queries       INTEGER,
                total_solver_calls  INTEGER,
                timestamp           TEXT
            )
            """
        )
        conn.commit()
        conn.close()
