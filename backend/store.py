"""SQLite persistence for quotas, API keys, shares, vault, RAG, and routing stats."""
import hashlib
import json
import math
import os
import sqlite3
import threading
import time
from pathlib import Path

_lock = threading.Lock()
_db: sqlite3.Connection | None = None

DATA_DIR = Path(os.getenv("AXIOM_DATA_DIR") or Path(__file__).resolve().parent / "data")
DB_PATH = DATA_DIR / "axiom.db"


def _connect() -> sqlite3.Connection:
    global _db
    if _db is not None:
        return _db
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _db = sqlite3.connect(DB_PATH, check_same_thread=False)
    _db.row_factory = sqlite3.Row
    _db.execute("PRAGMA journal_mode=WAL")
    _db.executescript(
        """
        CREATE TABLE IF NOT EXISTS quotas (
            client TEXT NOT NULL,
            day TEXT NOT NULL,
            requests INTEGER NOT NULL DEFAULT 0,
            tokens INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (client, day)
        );
        CREATE TABLE IF NOT EXISTS api_keys (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            hash TEXT NOT NULL UNIQUE,
            prefix TEXT NOT NULL,
            daily_requests INTEGER NOT NULL DEFAULT 200,
            daily_tokens INTEGER NOT NULL DEFAULT 500000,
            created REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS shares (
            id TEXT PRIMARY KEY,
            title TEXT,
            payload TEXT NOT NULL,
            created REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS vault (
            id TEXT PRIMARY KEY,
            owner TEXT NOT NULL DEFAULT 'legacy',
            ciphertext TEXT NOT NULL,
            updated REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS docs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner TEXT NOT NULL DEFAULT 'legacy',
            name TEXT NOT NULL,
            text TEXT NOT NULL,
            created REAL NOT NULL
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(name, text, content='docs', content_rowid='id');
        CREATE TABLE IF NOT EXISTS pdf_docs (
            id TEXT PRIMARY KEY,
            owner TEXT NOT NULL,
            name TEXT NOT NULL,
            created REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS pdf_docs_owner_idx ON pdf_docs(owner);
        CREATE TABLE IF NOT EXISTS pdf_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT NOT NULL REFERENCES pdf_docs(id) ON DELETE CASCADE,
            owner TEXT NOT NULL,
            page INTEGER NOT NULL,
            chunk_index INTEGER NOT NULL,
            text TEXT NOT NULL,
            vector TEXT,
            UNIQUE(doc_id, page, chunk_index)
        );
        CREATE INDEX IF NOT EXISTS pdf_chunks_owner_idx ON pdf_chunks(owner, doc_id);
        CREATE VIRTUAL TABLE IF NOT EXISTS pdf_chunks_fts USING fts5(
            doc_id UNINDEXED, owner UNINDEXED, name, page UNINDEXED, chunk_index UNINDEXED, text
        );
        CREATE TABLE IF NOT EXISTS latency (
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            ewma REAL NOT NULL,
            samples INTEGER NOT NULL,
            PRIMARY KEY (provider, model)
        );
        CREATE TRIGGER IF NOT EXISTS docs_ai AFTER INSERT ON docs BEGIN
            INSERT INTO docs_fts(rowid, name, text) VALUES (new.id, new.name, new.text);
        END;
        """
    )
    for table, column in (("vault", "owner"), ("docs", "owner")):
        columns = {row["name"] for row in _db.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            _db.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT NOT NULL DEFAULT 'legacy'")
    _db.execute("CREATE INDEX IF NOT EXISTS docs_owner_idx ON docs(owner)")
    _db.execute("PRAGMA foreign_keys=ON")
    _db.commit()
    return _db


def today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def bump_quota(client: str, requests: int = 1, tokens: int = 0) -> tuple[int, int]:
    with _lock:
        db = _connect()
        day = today()
        db.execute(
            "INSERT INTO quotas(client, day, requests, tokens) VALUES (?,?,?,?) "
            "ON CONFLICT(client, day) DO UPDATE SET requests = requests + ?, tokens = tokens + ?",
            (client, day, requests, tokens, requests, tokens),
        )
        row = db.execute(
            "SELECT requests, tokens FROM quotas WHERE client=? AND day=?",
            (client, day),
        ).fetchone()
        db.commit()
        return int(row["requests"]), int(row["tokens"])


def reserve_request(client: str, max_requests: int, max_tokens: int) -> tuple[int, int] | None:
    """Atomically checks and reserves one daily request against the configured quota."""
    with _lock:
        db = _connect()
        day = today()
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT requests, tokens FROM quotas WHERE client=? AND day=?",
            (client, day),
        ).fetchone()
        requests = int(row["requests"]) if row else 0
        tokens = int(row["tokens"]) if row else 0
        if requests >= max_requests or tokens >= max_tokens:
            db.rollback()
            return None
        db.execute(
            "INSERT INTO quotas(client, day, requests, tokens) VALUES (?,?,1,0) "
            "ON CONFLICT(client, day) DO UPDATE SET requests=requests+1",
            (client, day),
        )
        db.commit()
        return requests + 1, tokens


def quota_usage(client: str) -> tuple[int, int]:
    with _lock:
        db = _connect()
        row = db.execute(
            "SELECT requests, tokens FROM quotas WHERE client=? AND day=?",
            (client, today()),
        ).fetchone()
        if not row:
            return 0, 0
        return int(row["requests"]), int(row["tokens"])


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create_api_key(name: str, raw: str, daily_requests: int = 200, daily_tokens: int = 500_000) -> dict:
    import secrets

    raw = raw or ("axm_" + secrets.token_urlsafe(24))
    with _lock:
        db = _connect()
        kid = secrets.token_hex(8)
        db.execute(
            "INSERT INTO api_keys(id, name, hash, prefix, daily_requests, daily_tokens, created) "
            "VALUES (?,?,?,?,?,?,?)",
            (kid, name[:80], hash_key(raw), raw[:8], daily_requests, daily_tokens, time.time()),
        )
        db.commit()
    return {"id": kid, "name": name, "key": raw, "prefix": raw[:8]}


def lookup_api_key(raw: str) -> dict | None:
    if not raw:
        return None
    with _lock:
        db = _connect()
        row = db.execute("SELECT * FROM api_keys WHERE hash=?", (hash_key(raw),)).fetchone()
        if not row:
            return None
        return dict(row)


def list_api_keys() -> list[dict]:
    with _lock:
        db = _connect()
        rows = db.execute(
            "SELECT id, name, prefix, daily_requests, daily_tokens, created FROM api_keys ORDER BY created DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def delete_api_key(kid: str) -> bool:
    with _lock:
        db = _connect()
        result = db.execute("DELETE FROM api_keys WHERE id=?", (kid,))
        db.commit()
        return result.rowcount > 0


def save_share(sid: str, title: str, payload: dict) -> None:
    with _lock:
        db = _connect()
        db.execute(
            "INSERT OR REPLACE INTO shares(id, title, payload, created) VALUES (?,?,?,?)",
            (sid, title[:120], json.dumps(payload), time.time()),
        )
        db.commit()


def get_share(sid: str) -> dict | None:
    with _lock:
        db = _connect()
        row = db.execute("SELECT title, payload, created FROM shares WHERE id=?", (sid,)).fetchone()
        if not row:
            return None
        data = json.loads(row["payload"])
        data["title"] = row["title"]
        data["created"] = row["created"]
        return data


def _scoped_id(owner: str, vid: str) -> str:
    return f"{hashlib.sha256(owner.encode()).hexdigest()[:20]}:{vid}"


def put_vault(owner: str, vid: str, ciphertext: str) -> None:
    with _lock:
        db = _connect()
        db.execute(
            "INSERT OR REPLACE INTO vault(id, owner, ciphertext, updated) VALUES (?,?,?,?)",
            (_scoped_id(owner, vid), owner, ciphertext, time.time()),
        )
        db.commit()


def get_vault(owner: str, vid: str) -> str | None:
    with _lock:
        db = _connect()
        row = db.execute(
            "SELECT ciphertext FROM vault WHERE owner=? AND id=?",
            (owner, _scoped_id(owner, vid)),
        ).fetchone()
        return None if not row else row["ciphertext"]


def index_document(owner: str, name: str, text: str) -> int:
    with _lock:
        db = _connect()
        cur = db.execute(
            "INSERT INTO docs(owner, name, text, created) VALUES (?,?,?,?)",
            (owner, name[:120], text[:80_000], time.time()),
        )
        db.commit()
        return int(cur.lastrowid)


def rag_search(owner: str, query: str, n: int = 5) -> list[dict]:
    q = (query or "").strip()
    if not q:
        return []
    with _lock:
        db = _connect()
        try:
            rows = db.execute(
                "SELECT docs.name AS name, snippet(docs_fts, 1, '', '', ' … ', 24) AS snippet, "
                "substr(docs.text, 1, 800) AS text "
                "FROM docs_fts JOIN docs ON docs.id = docs_fts.rowid "
                "WHERE docs_fts MATCH ? AND docs.owner=? LIMIT ?",
                (q, owner, n),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [dict(r) for r in rows]


def create_pdf_document(owner: str, doc_id: str, name: str) -> None:
    with _lock:
        db = _connect()
        db.execute(
            "INSERT INTO pdf_docs(id, owner, name, created) VALUES (?,?,?,?)",
            (doc_id, owner, name[:120], time.time()),
        )
        db.commit()


def add_pdf_chunks(owner: str, doc_id: str, chunks: list[dict]) -> int:
    with _lock:
        db = _connect()
        document = db.execute(
            "SELECT name FROM pdf_docs WHERE id=? AND owner=?", (doc_id, owner)
        ).fetchone()
        if not document:
            return 0
        inserted = 0
        try:
            for chunk in chunks:
                vector = chunk.get("vector")
                cur = db.execute(
                    "INSERT INTO pdf_chunks(doc_id, owner, page, chunk_index, text, vector) "
                    "VALUES (?,?,?,?,?,?)",
                    (
                        doc_id,
                        owner,
                        int(chunk["page"]),
                        int(chunk["chunk_index"]),
                        str(chunk["text"]),
                        json.dumps(vector) if vector is not None else None,
                    ),
                )
                db.execute(
                    "INSERT INTO pdf_chunks_fts(rowid, doc_id, owner, name, page, chunk_index, text) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (
                        cur.lastrowid,
                        doc_id,
                        owner,
                        document["name"],
                        int(chunk["page"]),
                        int(chunk["chunk_index"]),
                        str(chunk["text"]),
                    ),
                )
                inserted += 1
            db.commit()
        except Exception:
            db.rollback()
            raise
        return inserted


def list_pdf_documents(owner: str) -> list[dict]:
    with _lock:
        rows = _connect().execute(
            "SELECT d.id, d.name, d.created, COUNT(c.id) AS chunks "
            "FROM pdf_docs d LEFT JOIN pdf_chunks c ON c.doc_id=d.id AND c.owner=d.owner "
            "WHERE d.owner=? GROUP BY d.id ORDER BY d.created DESC",
            (owner,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_pdf_document(owner: str, doc_id: str) -> dict | None:
    with _lock:
        row = _connect().execute(
            "SELECT id, name, created FROM pdf_docs WHERE owner=? AND id=?",
            (owner, doc_id),
        ).fetchone()
        return dict(row) if row else None


def get_pdf_chunks(owner: str, doc_id: str | None = None) -> list[dict]:
    with _lock:
        db = _connect()
        if doc_id is None:
            rows = db.execute(
                "SELECT c.id, c.doc_id, d.name, c.page, c.chunk_index, c.text, c.vector "
                "FROM pdf_chunks c JOIN pdf_docs d ON d.id=c.doc_id AND d.owner=c.owner "
                "WHERE c.owner=? ORDER BY d.created, c.page, c.chunk_index",
                (owner,),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT c.id, c.doc_id, d.name, c.page, c.chunk_index, c.text, c.vector "
                "FROM pdf_chunks c JOIN pdf_docs d ON d.id=c.doc_id AND d.owner=c.owner "
                "WHERE c.owner=? AND c.doc_id=? ORDER BY c.page, c.chunk_index",
                (owner, doc_id),
            ).fetchall()
        return [
            {**dict(row), "vector": json.loads(row["vector"]) if row["vector"] else None}
            for row in rows
        ]


def set_pdf_vectors(owner: str, doc_id: str, vectors: list[list[float] | None]) -> None:
    with _lock:
        db = _connect()
        rows = db.execute(
            "SELECT id FROM pdf_chunks WHERE owner=? AND doc_id=? ORDER BY page, chunk_index",
            (owner, doc_id),
        ).fetchall()
        if len(rows) != len(vectors):
            raise ValueError("Vector count does not match the stored PDF chunks.")
        try:
            db.executemany(
                "UPDATE pdf_chunks SET vector=? WHERE id=? AND owner=?",
                [
                    (json.dumps(vector) if vector is not None else None, row["id"], owner)
                    for row, vector in zip(rows, vectors)
                ],
            )
            db.commit()
        except Exception:
            db.rollback()
            raise


def delete_pdf_document(owner: str, doc_id: str) -> bool:
    with _lock:
        db = _connect()
        rows = db.execute(
            "SELECT id FROM pdf_chunks WHERE owner=? AND doc_id=?", (owner, doc_id)
        ).fetchall()
        if not rows:
            exists = db.execute(
                "SELECT 1 FROM pdf_docs WHERE owner=? AND id=?", (owner, doc_id)
            ).fetchone()
            if not exists:
                return False
        try:
            db.executemany("DELETE FROM pdf_chunks_fts WHERE rowid=?", [(row["id"],) for row in rows])
            db.execute("DELETE FROM pdf_chunks WHERE owner=? AND doc_id=?", (owner, doc_id))
            db.execute("DELETE FROM pdf_docs WHERE owner=? AND id=?", (owner, doc_id))
            db.commit()
        except Exception:
            db.rollback()
            raise
        return True


def pdf_hybrid_search(
    owner: str,
    query: str,
    query_vector: list[float] | None,
    n: int = 6,
    doc_ids: list[str] | None = None,
) -> list[dict]:
    import re

    with _lock:
        db = _connect()
        all_rows = db.execute(
            "SELECT c.id, c.doc_id, d.name, c.page, c.chunk_index, c.text, c.vector "
            "FROM pdf_chunks c JOIN pdf_docs d ON d.id=c.doc_id AND d.owner=c.owner "
            "WHERE c.owner=? ORDER BY c.id",
            (owner,),
        ).fetchall()
        rows = [
            {**dict(row), "vector": json.loads(row["vector"]) if row["vector"] else None}
            for row in all_rows
            if doc_ids is None or row["doc_id"] in doc_ids
        ]
        if not rows:
            return []

        query_words = list(dict.fromkeys(re.findall(r"[\w]+", query.lower())))
        fts_rows: list[sqlite3.Row] = []
        if query_words:
            fts_query = " OR ".join(f'"{word.replace(chr(34), "")}"' for word in query_words[:32])
            try:
                sql = (
                    "SELECT rowid FROM pdf_chunks_fts WHERE pdf_chunks_fts MATCH ? AND owner=? "
                )
                params: list = [fts_query, owner]
                if doc_ids is not None:
                    placeholders = ",".join("?" for _ in doc_ids)
                    sql += f" AND doc_id IN ({placeholders})"
                    params.extend(doc_ids)
                sql += " ORDER BY bm25(pdf_chunks_fts)"
                fts_rows = db.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                fts_rows = []

    by_id = {int(row["id"]): row for row in rows}
    ranks: dict[int, float] = {}
    fts_rank = {int(row["rowid"]): rank for rank, row in enumerate(fts_rows, 1)}
    vector_rank: dict[int, tuple[int, float]] = {}
    if query_vector:
        qnorm = math.sqrt(sum(float(value) ** 2 for value in query_vector))
        if qnorm:
            similarities = []
            for row in rows:
                vector = row["vector"]
                if not vector or len(vector) != len(query_vector):
                    continue
                vector_norm = math.sqrt(sum(float(value) ** 2 for value in vector))
                if not vector_norm:
                    continue
                score = sum(
                    float(value) * float(query_value)
                    for value, query_value in zip(vector, query_vector)
                ) / (vector_norm * qnorm)
                similarities.append((int(row["id"]), score))
            similarities.sort(key=lambda item: item[1], reverse=True)
            vector_rank = {
                chunk_id: (rank, score)
                for rank, (chunk_id, score) in enumerate(similarities, 1)
            }

    for chunk_id in by_id:
        if chunk_id not in fts_rank and chunk_id not in vector_rank:
            continue
        score = 0.0
        if chunk_id in fts_rank:
            score += 1.0 / (60 + fts_rank[chunk_id])
        if chunk_id in vector_rank:
            score += 1.0 / (60 + vector_rank[chunk_id][0])
        ranks[chunk_id] = score
    ordered = sorted(ranks, key=ranks.get, reverse=True)[:n]
    return [
        {
            **{key: value for key, value in by_id[chunk_id].items() if key != "vector"},
            "score": ranks[chunk_id],
            "similarity": vector_rank.get(chunk_id, (0, 0.0))[1],
            "fts_rank": fts_rank.get(chunk_id),
        }
        for chunk_id in ordered
    ]


def record_latency(provider: str, model: str, ms: float) -> None:
    with _lock:
        db = _connect()
        row = db.execute(
            "SELECT ewma, samples FROM latency WHERE provider=? AND model=?",
            (provider, model),
        ).fetchone()
        if row:
            ewma = 0.3 * ms + 0.7 * float(row["ewma"])
            samples = int(row["samples"]) + 1
            db.execute(
                "UPDATE latency SET ewma=?, samples=? WHERE provider=? AND model=?",
                (ewma, samples, provider, model),
            )
        else:
            db.execute(
                "INSERT INTO latency(provider, model, ewma, samples) VALUES (?,?,?,1)",
                (provider, model, ms),
            )
        db.commit()


def latency_map() -> dict[tuple[str, str], float]:
    with _lock:
        db = _connect()
        rows = db.execute("SELECT provider, model, ewma FROM latency").fetchall()
        return {(r["provider"], r["model"]): float(r["ewma"]) for r in rows}
