"""
SQLite persistence layer for Lotus Electronics chatbot.

Replaces Redis for durable data since Redis is optional/often down here. Stores:
  - sessions   : one row per chat session (id, timestamps, message count)
  - chat_logs  : every user/assistant message (powers the admin transcript view)
  - tickets and bulk enquiries raised through the chatbot

Uses a fresh short-lived connection per call so it is safe under Flask's threaded
dev server. All functions are defensive: a DB error is logged and swallowed so
persistence never breaks the chat.
"""

import os
import json
import random
import hashlib
import uuid
from contextlib import closing
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lotus_app.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables if they don't exist. Safe to call repeatedly."""
    try:
        with closing(_connect()) as conn, conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id    TEXT PRIMARY KEY,
                    created_at    TEXT NOT NULL,
                    last_active   TEXT NOT NULL,
                    message_count INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS chat_logs (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role       TEXT NOT NULL,
                    message    TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_chat_logs_session
                    ON chat_logs(session_id);
                CREATE TABLE IF NOT EXISTS chat_responses (
                    message_id INTEGER PRIMARY KEY,
                    response_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tickets (
                    ticket_id   TEXT PRIMARY KEY,
                    session_id  TEXT,
                    name        TEXT,
                    phone       TEXT,
                    issue       TEXT,
                    status      TEXT,
                    created_at  TEXT
                );

                CREATE TABLE IF NOT EXISTS bulk_enquiries (
                    enquiry_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(session_id, fingerprint)
                );
                CREATE TABLE IF NOT EXISTS bulk_enquiry_drafts (
                    session_id TEXT PRIMARY KEY,
                    draft_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    shown_message_id INTEGER,
                    created_at TEXT NOT NULL
                );
                """
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
            if "source" not in columns:
                conn.execute("ALTER TABLE sessions ADD COLUMN source TEXT NOT NULL DEFAULT 'unknown'")
    except Exception as e:  # pragma: no cover - defensive
        print(f"❌ store.init_db failed: {type(e).__name__}: {e}")


# --------------------------------------------------------------------------- #
# Chat logging / sessions
# --------------------------------------------------------------------------- #
def log_message(session_id: str, role: str, message: str, response_json: Optional[str] = None) -> Optional[int]:
    """Record one message and upsert its session row."""
    if not session_id or not message:
        return
    now = datetime.utcnow().isoformat()
    try:
        with closing(_connect()) as conn, conn:
            cursor = conn.execute(
                "INSERT INTO chat_logs (session_id, role, message, created_at) "
                "VALUES (?, ?, ?, ?)",
                (session_id, role, message, now),
            )
            if role == "assistant" and response_json:
                conn.execute("INSERT INTO chat_responses VALUES (?, ?)", (cursor.lastrowid, response_json))
            conn.execute(
                """
                INSERT INTO sessions (session_id, created_at, last_active, message_count)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(session_id) DO UPDATE SET
                    last_active = excluded.last_active,
                    message_count = message_count + 1
                """,
                (session_id, now, now),
            )
        return cursor.lastrowid
    except Exception as e:  # pragma: no cover - defensive
        print(f"❌ store.log_message failed: {type(e).__name__}: {e}")


def record_session_source(session_id: str, source: str) -> None:
    """Record the client-reported origin once; do not guess historic origins."""
    if source not in {"web", "app", "unknown"}:
        raise ValueError("source must be web, app or unknown")
    now = datetime.utcnow().isoformat()
    try:
        with closing(_connect()) as conn, conn:
            conn.execute(
                "INSERT INTO sessions (session_id,created_at,last_active,message_count,source) "
                "VALUES (?,?,?,0,?) ON CONFLICT(session_id) DO UPDATE SET "
                "source=CASE WHEN sessions.source='unknown' THEN excluded.source ELSE sessions.source END",
                (session_id, now, now, source),
            )
    except Exception as e:
        print(f"store.record_session_source failed: {type(e).__name__}: {e}")


def get_sessions() -> List[Dict[str, Any]]:
    try:
        with closing(_connect()) as conn, conn:
            rows = conn.execute(
                "SELECT session_id, created_at, last_active, message_count, source "
                "FROM sessions ORDER BY last_active DESC"
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception as e:  # pragma: no cover - defensive
        print(f"❌ store.get_sessions failed: {type(e).__name__}: {e}")
        return []


def get_chat_logs(session_id: str) -> List[Dict[str, Any]]:
    """Return a transcript plus image URLs from each saved structured response.

    Product cards are persisted in ``chat_responses.response_json``.  Exposing
    their images here lets session viewers rebuild what the customer actually
    saw instead of returning only the assistant's plain-text answer.
    """
    try:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT l.id, l.role, l.message, l.created_at, r.response_json "
                "FROM chat_logs l LEFT JOIN chat_responses r ON r.message_id = l.id "
                "WHERE session_id = ? ORDER BY id ASC",
                (session_id,),
            ).fetchall()
            messages = []
            for row in rows:
                item = dict(row)
                raw_response = item.pop("response_json", None)
                item["result_images"] = _result_images(raw_response)
                messages.append(item)
            return messages
    except Exception as e:  # pragma: no cover - defensive
        print(f"❌ store.get_chat_logs failed: {type(e).__name__}: {e}")
        return []


def _result_images(response_json: Optional[str]) -> List[Dict[str, str]]:
    """Extract unique card images from a response already stored in SQLite."""
    if not response_json:
        return []
    try:
        response = json.loads(response_json)
    except (TypeError, ValueError):
        return []
    if not isinstance(response, dict):
        return []

    candidates = []
    for key in ("products", "recommendations"):
        value = response.get(key)
        if isinstance(value, list):
            candidates.extend(item for item in value if isinstance(item, dict))
    detail = response.get("product_details")
    if isinstance(detail, dict) and detail:
        candidates.append(detail)
    comparison = response.get("comparison")
    if isinstance(comparison, list):
        candidates.extend(item for item in comparison if isinstance(item, dict))

    images = []
    seen = set()
    for item in candidates:
        base_name = str(item.get("product_name") or item.get("name") or "Product result")
        image_fields = [(item.get("product_image") or item.get("image_url") or
                         item.get("image") or item.get("first_image"), base_name)]
        # Comparison cards carry two independent product images.
        image_fields.extend([
            (item.get("image_a"), str(item.get("name_a") or base_name)),
            (item.get("image_b"), str(item.get("name_b") or base_name)),
        ])
        for image, name in image_fields:
            if isinstance(image, list):
                image = next((entry for entry in image if isinstance(entry, str) and entry.strip()), "")
            if not isinstance(image, str) or not image.strip() or image.strip() in seen:
                continue
            image = image.strip()
            seen.add(image)
            images.append({"url": image, "name": name})
    return images


def get_stats() -> Dict[str, int]:
    try:
        with _connect() as conn:
            sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            messages = conn.execute("SELECT COUNT(*) FROM chat_logs").fetchone()[0]
            tickets = conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
            bulk = conn.execute("SELECT COUNT(*) FROM bulk_enquiries").fetchone()[0]
            return {"sessions": sessions, "messages": messages, "tickets": tickets, "bulk_enquiries": bulk}
    except Exception as e:  # pragma: no cover - defensive
        print(f"❌ store.get_stats failed: {type(e).__name__}: {e}")
        return {"sessions": 0, "messages": 0, "tickets": 0, "bulk_enquiries": 0}


def get_chat_context(session_id: str, limit: int = 40) -> List[Dict[str, Any]]:
    """Canonical, ordered conversation including the product cards actually shown."""
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT l.id,l.role,l.message,r.response_json FROM chat_logs l "
            "LEFT JOIN chat_responses r ON r.message_id=l.id "
            "WHERE l.session_id=? ORDER BY l.id DESC LIMIT ?", (session_id, limit)
        ).fetchall()
        return [dict(row) for row in reversed(rows)]


def create_bulk_enquiry(session_id: str, details: Dict[str, Any]) -> Dict[str, Any]:
    """Commit a quotation request; identical retries in a session reuse its ID."""
    canonical = json.dumps(details, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    created = datetime.utcnow().isoformat()
    record = {
        **details,
        "enquiry_id": "BULK-" + uuid.uuid4().hex[:12].upper(),
        "status": "Quotation pending",
        "created_at": created,
        "purchase_confirmed": False,
        "notice": "Enquiry saved. Bulk pricing, stock and delivery require confirmation. No purchase has been placed.",
    }
    try:
        with closing(_connect()) as conn, conn:
            conn.execute(
                "INSERT OR IGNORE INTO bulk_enquiries "
                "(enquiry_id, session_id, fingerprint, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (record["enquiry_id"], session_id, fingerprint, json.dumps(record, ensure_ascii=False), created),
            )
            row = conn.execute(
                "SELECT payload_json FROM bulk_enquiries WHERE session_id = ? AND fingerprint = ?",
                (session_id, fingerprint),
            ).fetchone()
            saved = json.loads(row["payload_json"])
        return saved  # Only after transaction commit succeeds.
    except Exception:
        return {"error": "Your bulk enquiry could not be saved. No order was placed. Please try again.",
                "error_code": "bulk_enquiry_save_failed"}


def get_bulk_enquiries() -> List[Dict[str, Any]]:
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT payload_json FROM bulk_enquiries ORDER BY created_at DESC").fetchall()
        return [json.loads(row["payload_json"]) for row in rows]


def save_bulk_draft(session_id: str, details: dict) -> dict:
    draft = {"draft_id": "DRAFT-" + uuid.uuid4().hex, "details": details}
    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT INTO bulk_enquiry_drafts VALUES (?, ?, ?, NULL, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET draft_id=excluded.draft_id, "
            "payload_json=excluded.payload_json, shown_message_id=NULL, created_at=excluded.created_at",
            (session_id, draft["draft_id"], json.dumps(details, ensure_ascii=False), datetime.utcnow().isoformat()),
        )
    return draft


def get_bulk_draft(session_id: str) -> dict:
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM bulk_enquiry_drafts WHERE session_id=?", (session_id,)).fetchone()
        if not row:
            return {}
        return {**dict(row), "details": json.loads(row["payload_json"])}


def mark_bulk_draft_shown(session_id: str, draft_id: str, message_id: int) -> None:
    with closing(_connect()) as conn, conn:
        conn.execute("UPDATE bulk_enquiry_drafts SET shown_message_id=? WHERE session_id=? AND draft_id=?",
                     (message_id, session_id, draft_id))


# --------------------------------------------------------------------------- #
# Orders
# --------------------------------------------------------------------------- #
_STATUS_FLOW = ["Order Placed", "Processing", "Shipped", "Out for Delivery", "Delivered"]


def _build_timeline(current_status: str, order_dt: datetime) -> List[Dict[str, str]]:
    """Return a timeline marking each stage done/current/pending."""
    try:
        idx = _STATUS_FLOW.index(current_status)
    except ValueError:
        idx = 0
    timeline = []
    for i, stage in enumerate(_STATUS_FLOW):
        if i < idx:
            state = "done"
        elif i == idx:
            state = "current"
        else:
            state = "pending"
        stage_dt = order_dt + timedelta(days=i)
        timeline.append({"stage": stage, "state": state, "date": stage_dt.strftime("%d %b %Y")})
    return timeline


def _row_to_order(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    try:
        d["timeline"] = json.loads(d.pop("timeline_json") or "[]")
    except Exception:
        d["timeline"] = []
    return d


def create_order(session_id: Optional[str], product: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new order for a product dict (from catalog._public_view)."""
    order_id = "LOTUS" + str(random.randint(10000, 99999))
    order_dt = datetime.utcnow()
    status = "Processing"
    expected = (order_dt + timedelta(days=4)).strftime("%d %b %Y")
    timeline = _build_timeline(status, order_dt)
    record = {
        "order_id": order_id,
        "session_id": session_id,
        "product_id": str(product.get("product_id", "")),
        "product_name": product.get("product_name", "Product"),
        "amount": product.get("product_mrp", ""),
        "status": status,
        "order_date": order_dt.strftime("%d %b %Y"),
        "expected_delivery": expected,
        "timeline_json": json.dumps(timeline),
    }
    try:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO orders (order_id, session_id, product_id, product_name, "
                "amount, status, order_date, expected_delivery, timeline_json) "
                "VALUES (:order_id, :session_id, :product_id, :product_name, :amount, "
                ":status, :order_date, :expected_delivery, :timeline_json)",
                record,
            )
    except Exception as e:  # pragma: no cover - defensive
        print(f"❌ store.create_order failed: {type(e).__name__}: {e}")
        return {"error": "The order could not be saved. Please try again.",
                "error_code": "order_creation_failed"}
    out = dict(record)
    out["timeline"] = timeline
    out.pop("timeline_json", None)
    return out


def get_order(order_id: str) -> Optional[Dict[str, Any]]:
    if not order_id:
        return None
    oid = order_id.strip().upper()
    if not oid.startswith("LOTUS"):
        oid = "LOTUS" + oid.lstrip("#").strip()
    try:
        with _connect() as conn:
            row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (oid,)).fetchone()
            return _row_to_order(row) if row else None
    except Exception as e:  # pragma: no cover - defensive
        print(f"❌ store.get_order failed: {type(e).__name__}: {e}")
        return None


def get_orders() -> List[Dict[str, Any]]:
    try:
        with _connect() as conn:
            rows = conn.execute("SELECT * FROM orders ORDER BY rowid DESC").fetchall()
            return [_row_to_order(r) for r in rows]
    except Exception as e:  # pragma: no cover - defensive
        print(f"❌ store.get_orders failed: {type(e).__name__}: {e}")
        return []


def seed_orders() -> None:
    """Insert a few dummy orders once, so tracking works out of the box."""
    try:
        with _connect() as conn:
            existing = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
            if existing:
                return
    except Exception as e:  # pragma: no cover - defensive
        print(f"❌ store.seed_orders check failed: {type(e).__name__}: {e}")
        return

    samples = [
        ("LOTUS1001", "40089", "Samsung Galaxy A26 5G (6GB/128GB) White", "₹21,557", "Delivered", 9),
        ("LOTUS1002", "41002", "Samsung 43 inch 4K Ultra HD Smart LED TV", "₹32,990", "Out for Delivery", 3),
        ("LOTUS1003", "42010", "HP Pavilion 15 (i5, 16GB, 512GB SSD)", "₹61,990", "Shipped", 2),
        ("LOTUS1004", "43001", "LG 1.5 Ton 5 Star Dual Inverter Split AC", "₹42,990", "Processing", 1),
    ]
    for order_id, pid, name, amount, status, days_ago in samples:
        order_dt = datetime.utcnow() - timedelta(days=days_ago)
        expected = (order_dt + timedelta(days=4)).strftime("%d %b %Y")
        timeline = _build_timeline(status, order_dt)
        record = {
            "order_id": order_id,
            "session_id": "seed",
            "product_id": pid,
            "product_name": name,
            "amount": amount,
            "status": status,
            "order_date": order_dt.strftime("%d %b %Y"),
            "expected_delivery": expected,
            "timeline_json": json.dumps(timeline),
        }
        try:
            with _connect() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO orders (order_id, session_id, product_id, "
                    "product_name, amount, status, order_date, expected_delivery, "
                    "timeline_json) VALUES (:order_id, :session_id, :product_id, "
                    ":product_name, :amount, :status, :order_date, :expected_delivery, "
                    ":timeline_json)",
                    record,
                )
        except Exception as e:  # pragma: no cover - defensive
            print(f"❌ store.seed_orders insert failed: {type(e).__name__}: {e}")


# --------------------------------------------------------------------------- #
# Support tickets
# --------------------------------------------------------------------------- #
def create_ticket(session_id: Optional[str], name: str, phone: str, issue: str) -> Dict[str, Any]:
    """Create a support ticket and return it."""
    created = datetime.utcnow()
    record = {
        "session_id": session_id,
        "name": (name or "").strip(),
        "phone": (phone or "").strip(),
        "issue": (issue or "").strip(),
        "status": "Open",
        "created_at": created.isoformat(),
    }
    try:
        with closing(_connect()) as conn, conn:
            # Allocate and insert under the same lock across all Gunicorn workers.
            # A failed insert rolls back the counter as well as the ticket.
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("CREATE TABLE IF NOT EXISTS ticket_sequence "
                         "(id INTEGER PRIMARY KEY CHECK (id = 1), last_number INTEGER NOT NULL)")
            sequence = conn.execute("SELECT last_number FROM ticket_sequence WHERE id=1").fetchone()
            if sequence is None:
                highest = 1000
                for row in conn.execute("SELECT ticket_id FROM tickets WHERE ticket_id LIKE 'TCKT-%'"):
                    suffix = row[0][5:]
                    if suffix.isascii() and suffix.isdigit():
                        highest = max(highest, int(suffix))
                conn.execute("INSERT INTO ticket_sequence VALUES (1, ?)", (highest,))
            conn.execute("UPDATE ticket_sequence SET last_number=last_number+1 WHERE id=1")
            number = conn.execute("SELECT last_number FROM ticket_sequence WHERE id=1").fetchone()[0]
            record["ticket_id"] = f"TCKT-{number:06d}"
            conn.execute(
                "INSERT INTO tickets (ticket_id, session_id, name, phone, issue, "
                "status, created_at) VALUES (:ticket_id, :session_id, :name, :phone, "
                ":issue, :status, :created_at)",
                record,
            )
    except Exception as e:  # pragma: no cover - defensive
        print(f"store.create_ticket failed: {type(e).__name__}: {e}")
        return {"error": "The ticket could not be saved. Please try again.",
                "error_code": "ticket_creation_failed"}
    out = dict(record)
    out["created_date"] = created.strftime("%d %b %Y, %I:%M %p")
    return out


def get_tickets() -> List[Dict[str, Any]]:
    try:
        with _connect() as conn:
            rows = conn.execute("SELECT * FROM tickets ORDER BY rowid DESC").fetchall()
            return [dict(r) for r in rows]
    except Exception as e:  # pragma: no cover - defensive
        print(f"❌ store.get_tickets failed: {type(e).__name__}: {e}")
        return []
