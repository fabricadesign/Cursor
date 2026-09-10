"""Conversation store using Upstash Redis.

Stores conversation history and human takeover state per phone number.
Falls back to in-memory dict when Redis is not configured.
"""

import json
from datetime import datetime, timedelta, timezone
from config import settings

_memory_store: dict[str, dict] = {}
_redis = None


def now_iso() -> str:
    """Current UTC time as an ISO-8601 string, for message timestamps."""
    return datetime.now(timezone.utc).isoformat()


def _get_redis():
    global _redis
    if _redis is not None:
        return _redis
    if settings.kv_rest_api_url and settings.kv_rest_api_token:
        from upstash_redis import Redis
        _redis = Redis(url=settings.kv_rest_api_url, token=settings.kv_rest_api_token)
        return _redis
    return None


def _key(phone: str) -> str:
    return f"conv:{phone}"


def redis_healthy() -> bool:
    """Cheap liveness check for Redis (catches the over-limit / down cases)."""
    redis = _get_redis()
    if not redis:
        return True  # in-memory fallback is always 'healthy'
    try:
        redis.get("healthcheck")
        return True
    except Exception:
        return False


_INCIDENTS_KEY = "incidents"
_incidents_mem: list = []


def log_incident(kind: str, detail: str):
    """Record an operational problem (failed delivery, email poll error, etc.)
    into a short rolling log the dashboard's Problems view reads."""
    entry = json.dumps({"ts": now_iso(), "kind": kind, "detail": (detail or "")[:300]})
    redis = _get_redis()
    try:
        if redis:
            redis.lpush(_INCIDENTS_KEY, entry)
            redis.ltrim(_INCIDENTS_KEY, 0, 49)
        else:
            _incidents_mem.insert(0, entry)
            del _incidents_mem[50:]
    except Exception:
        pass


def get_incidents() -> list[dict]:
    redis = _get_redis()
    raw = []
    try:
        raw = redis.lrange(_INCIDENTS_KEY, 0, 49) if redis else list(_incidents_mem)
    except Exception:
        raw = []
    out = []
    for r in raw:
        try:
            out.append(json.loads(r) if isinstance(r, str) else r)
        except (ValueError, TypeError):
            continue
    return out


# A single Redis HASH holding a lightweight summary of every conversation,
# keyed by phone. The dashboard reads this ONE key (HGETALL = 1 command)
# instead of scanning every conversation (KEYS + a GET each), which was
# burning through the Upstash request limit on every auto-refresh.
_INDEX_KEY = "conv_index"


def customer_window_open(state: dict, now: datetime | None = None) -> bool:
    """True when a customer inbound in this thread is still inside Meta's 24h window.

    WhatsApp Cloud API only delivers a free-form text inside that window.
    A template does not open it — only the customer messaging the WABA does.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    for msg in reversed(state.get("messages") or []):
        if msg.get("role") != "customer":
            continue
        raw = msg.get("ts") or ""
        try:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        return dt >= cutoff
    return False


def _summary_from_state(state: dict) -> dict:
    """Build the lightweight dashboard summary stored in the index."""
    messages = state.get("messages", [])
    last_delivery = ""
    last_delivery_error = ""
    last_customer_ts = ""
    found_outbound = False
    for m in reversed(messages):
        if not found_outbound and m.get("role") in ("assistant", "human"):
            last_delivery = m.get("delivery") or ""
            last_delivery_error = m.get("delivery_error") or ""
            found_outbound = True
        if not last_customer_ts and m.get("role") == "customer":
            last_customer_ts = m.get("ts") or ""
        if found_outbound and last_customer_ts:
            break
    return {
        "last_delivery": last_delivery,
        "last_delivery_error": last_delivery_error,
        "name": state.get("customer_name", ""),
        "mode": state.get("mode", "agent"),
        "channel": state.get("channel", "whatsapp"),
        "subject": state.get("email_subject", ""),
        "summary": state.get("escalation_summary", ""),
        "message_count": len(messages),
        "last_customer_text": _last_customer_text(messages),
        "last_customer_ts": last_customer_ts,
        "last_ts": messages[-1].get("ts", "") if messages else "",
        "created_ts": messages[0].get("ts", "") if messages else "",
        "escalations": state.get("escalations", []),
    }


def _default_state() -> dict:
    return {
        "messages": [],
        "mode": "agent",  # "agent" or "human"
        "channel": "whatsapp",  # "whatsapp" or "email"
        "escalation_summary": "",
        "customer_name": "",
        # Email-only threading metadata (used to keep replies in the same thread)
        "email_subject": "",
        "email_last_message_id": "",
        "email_references": "",
        "escalations": [],  # history of {"ts", "summary"} — one per escalation event, for analytics
        # A manually-typed opening message queued while the customer is
        # outside the 24h window (see main.py admin_new_conversation_send).
        # WhatsApp only allows free-form sends within that window — a template
        # message does NOT open it, only the customer replying does — so this
        # is held here and flushed as soon as their reply arrives.
        "pending_first_message": "",
    }


def set_customer_name(phone: str, name: str):
    """Store the customer's WhatsApp profile name on their conversation."""
    if not name:
        return
    state = get_conversation(phone)
    if state.get("customer_name") != name:
        state["customer_name"] = name
        save_conversation(phone, state)


# Conversations persist until deleted manually (no expiry). We keep a generous
# cap on stored messages per chat to protect Redis from unbounded growth.
MAX_MESSAGES = 500
# How many of the most recent messages to feed the LLM as context per reply.
LLM_CONTEXT_MESSAGES = 20


def get_conversation(phone: str) -> dict:
    redis = _get_redis()
    if redis:
        data = redis.get(_key(phone))
        if data:
            return json.loads(data) if isinstance(data, str) else data
        return _default_state()
    return _memory_store.get(phone, _default_state())


def save_conversation(phone: str, state: dict):
    state["messages"] = state["messages"][-MAX_MESSAGES:]
    redis = _get_redis()
    if redis:
        # No `ex` → the conversation never expires; it stays until deleted.
        redis.set(_key(phone), json.dumps(state))
        # Keep the dashboard index in sync (one small HSET).
        redis.hset(_INDEX_KEY, phone, json.dumps(_summary_from_state(state)))
    else:
        _memory_store[phone] = state


_wamid_map: dict[str, str] = {}
_DELIVERY_RANK = {"sent": 1, "delivered": 2, "read": 3, "failed": 4}


def set_wamid(wamid: str, phone: str):
    """Remember which conversation a sent WhatsApp message (wamid) belongs to,
    so its later delivery-status webhook can be matched back to the message."""
    if not wamid:
        return
    redis = _get_redis()
    if redis:
        redis.set(f"wamid:{wamid}", phone, ex=259200)  # 3 days
    else:
        _wamid_map[wamid] = phone


def get_wamid_phone(wamid: str) -> str:
    redis = _get_redis()
    if redis:
        return redis.get(f"wamid:{wamid}") or ""
    return _wamid_map.get(wamid, "")


def update_message_delivery(phone: str, wamid: str, status: str, error: str = "") -> bool:
    """Set the delivery status on the stored message with this wamid.
    Never downgrades (read stays read) except a 'failed' always wins."""
    state = get_conversation(phone)
    for msg in reversed(state.get("messages", [])):
        if msg.get("wamid") == wamid:
            cur = msg.get("delivery", "")
            if status == "failed" or _DELIVERY_RANK.get(status, 0) >= _DELIVERY_RANK.get(cur, 0):
                msg["delivery"] = status
                if error:
                    msg["delivery_error"] = error
                elif status != "failed":
                    msg.pop("delivery_error", None)
                save_conversation(phone, state)
                return True
            return False
    return False


def delete_conversation(phone: str):
    """Permanently delete a conversation (manual deletion from the dashboard)."""
    redis = _get_redis()
    if redis:
        redis.delete(_key(phone))
        redis.hdel(_INDEX_KEY, phone)
    else:
        _memory_store.pop(phone, None)


def set_mode(phone: str, mode: str, summary: str = ""):
    state = get_conversation(phone)
    state["mode"] = mode
    if summary:
        state["escalation_summary"] = summary
    save_conversation(phone, state)


def get_mode(phone: str) -> str:
    return get_conversation(phone).get("mode", "agent")


def list_escalated() -> list[dict]:
    """List all conversations currently in human mode (derived from list_all)."""
    return [c for c in list_all() if c.get("mode") == "human"]


def _last_customer_text(messages: list) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "customer":
            text = msg.get("text", "")
            if not text and msg.get("media"):
                return "\U0001F4F7 Photo"
            return text
    return ""


def _backfill_index(redis) -> dict:
    """One-time: build the index from existing conversations (a single KEYS
    scan) when the index is missing/empty, e.g. right after this optimisation
    is first deployed. Populates the index so later reads are O(1)."""
    summaries = {}
    for key in redis.keys("conv:*"):
        data = redis.get(key)
        if data:
            state = json.loads(data) if isinstance(data, str) else data
            summaries[key.replace("conv:", "")] = _summary_from_state(state)
    if summaries:
        redis.hset(_INDEX_KEY, values={p: json.dumps(s) for p, s in summaries.items()})
    return summaries


def list_all() -> list[dict]:
    """List ALL conversations (both agent and human mode), newest activity first.

    Reads a single index HASH (1 Redis command) instead of scanning every
    conversation, so dashboard auto-refreshes stay cheap.
    """
    redis = _get_redis()
    summaries = {}
    if redis:
        raw = redis.hgetall(_INDEX_KEY) or {}
        if not raw:
            # Index empty — backfill once from existing conversations.
            summaries = _backfill_index(redis)
        else:
            for phone, val in raw.items():
                try:
                    summaries[phone] = json.loads(val) if isinstance(val, str) else val
                except (ValueError, TypeError):
                    continue
    else:
        summaries = {p: _summary_from_state(s) for p, s in _memory_store.items()}

    results = []
    for phone, s in summaries.items():
        results.append({
            "phone": phone,
            "name": s.get("name", ""),
            "mode": s.get("mode", "agent"),
            "channel": s.get("channel", "whatsapp"),
            "subject": s.get("subject", ""),
            "summary": s.get("summary", ""),
            "message_count": s.get("message_count", 0),
            "last_customer_text": s.get("last_customer_text", ""),
            "last_ts": s.get("last_ts", ""),
            "created_ts": s.get("created_ts", ""),
            "escalations": s.get("escalations", []),
            "last_delivery": s.get("last_delivery", ""),
            "last_delivery_error": s.get("last_delivery_error", ""),
            "last_customer_ts": s.get("last_customer_ts", ""),
        })

    # Most recent activity first, then bring escalated (human) chats to the top
    # (stable sort preserves the recency order within each group).
    results.sort(key=lambda c: c["last_ts"] or "", reverse=True)
    results.sort(key=lambda c: c["mode"] != "human")
    return results


BACKUP_PATH = __import__("os").path.join(__import__("os").path.dirname(__file__), "data", "recovered_conversations.json")


def import_conversations(conversations: dict, overwrite: bool = True) -> int:
    """Write recovered threads into Redis or the in-memory store."""
    loaded = 0
    for phone, state in (conversations or {}).items():
        if not phone or not isinstance(state, dict):
            continue
        existing = get_conversation(phone)
        if existing.get("messages") and not overwrite:
            if len(existing.get("messages") or []) >= len(state.get("messages") or []):
                continue
        merged = {**_default_state(), **state}
        merged["messages"] = state.get("messages") or []
        save_conversation(phone, merged)
        loaded += 1
    return loaded


def load_disk_backup_if_empty() -> int:
    """If this process has no conversations, restore the recovered inbox dump."""
    if list_all():
        return 0
    import os
    path = BACKUP_PATH
    if not os.path.exists(path):
        return 0
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, ValueError):
        return 0
    convs = payload.get("conversations") if isinstance(payload, dict) else None
    if not convs:
        return 0
    return import_conversations(convs, overwrite=True)
