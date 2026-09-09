"""FastAPI server — WhatsApp webhook + admin dashboard."""

import logging
import html
import base64
from fastapi import FastAPI, Request, Query, Response, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from config import settings
import agent
import whatsapp
import store
import email_service
import email_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Fábrica Coffee Roasters — Support Agent")


# ─── WhatsApp Webhook ────────────────────────────────────────────────

@app.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_token == settings.whatsapp_verify_token:
        return Response(content=hub_challenge, media_type="text/plain")
    return Response(status_code=403)


# Photos are stored inline (base64) in the conversation record in Redis.
# Cap how large a raw image we'll embed, so one oversized photo can't blow
# past Upstash's per-value request size limit and break the whole save.
MAX_IMAGE_STORE_BYTES = 3 * 1024 * 1024  # 3MB raw (~4MB once base64-encoded)


@app.post("/webhook")
async def receive_message(request: Request):
    body = await request.json()

    parsed = whatsapp.extract_message(body)
    if not parsed:
        # Not a customer message — it may be a delivery-status event for a
        # message WE sent (sent/delivered/read/failed). Record it so the
        # dashboard can show whether our replies actually reached the customer.
        statuses = whatsapp.extract_statuses(body)
        for st in statuses:
            ph = store.get_wamid_phone(st["id"])
            logger.info("WhatsApp status '%s' for %s (matched conv: %s)", st["status"], st["id"][:20], ph or "none")
            if ph and st["status"]:
                store.update_message_delivery(ph, st["id"], st["status"])
                if st["status"] == "failed":
                    logger.warning("WhatsApp message to %s FAILED to deliver: %s", ph, st.get("error"))
                    store.log_incident("whatsapp_failed", f"To {ph}: {st.get('error') or 'not delivered'}")
        return {"status": "ignored"}

    phone, text, message_id, customer_name, media = parsed
    logger.info("Message from %s (%s): %s%s", phone, customer_name, text, " [+photo]" if media else "")

    # Remember the customer's WhatsApp name for the dashboard
    store.set_customer_name(phone, customer_name)

    # Fetch the photo now — WhatsApp's media URLs are short-lived, so this
    # can't be deferred. Store it inline so it stays viewable in the
    # dashboard for as long as the conversation is kept (WhatsApp itself only
    # retains media for a limited window).
    image_payload = None
    if media:
        try:
            image_bytes, mime_type = await whatsapp.download_media(media["id"])
            if len(image_bytes) > MAX_IMAGE_STORE_BYTES:
                logger.warning("Photo from %s too large to store (%d bytes) — skipping", phone, len(image_bytes))
                text = text or "[Foto recebida (demasiado grande para guardar) / Photo received (too large to store)]"
            else:
                image_payload = {
                    "mime_type": mime_type,
                    "data": base64.b64encode(image_bytes).decode("ascii"),
                }
        except Exception as e:
            logger.error("Failed to download photo from %s (media %s): %s", phone, media.get("id"), e)
            text = text or "[Foto recebida, mas não foi possível transferi-la / Photo received but could not be downloaded]"

    # This reply just opened (or re-opened) the 24h free-form window. If an
    # admin queued an opening message via "Start a new conversation" while
    # the customer was outside that window (see admin_new_conversation_send),
    # this is the first moment it can actually be delivered — send it now,
    # before anything else, so it lands ahead of Bea's reply to this message.
    pending_state = store.get_conversation(phone)
    pending_text = pending_state.get("pending_first_message")
    if pending_text:
        try:
            await whatsapp.send_message(phone, pending_text)
            pending_state["messages"].append({"role": "human", "text": pending_text, "ts": store.now_iso()})
            pending_state["pending_first_message"] = ""
            store.save_conversation(phone, pending_state)
        except Exception as e:
            # Leave it queued so it's retried on the customer's next message
            # rather than silently lost.
            logger.error("Failed to flush queued opening message to %s: %s", phone, e)

    # Show the "typing..." indicator only when Bea (agent mode) will actually
    # reply. In human mode she stays silent for the team, so no typing dots.
    if message_id and store.get_mode(phone) != "human":
        await whatsapp.mark_read_and_typing(message_id)

    try:
        reply = await agent.chat(phone, text, media=image_payload)
        if reply:
            resp = await whatsapp.send_message(phone, reply)
            # Tag Bea's stored reply with its wamid so its delivery status
            # (delivered/read/failed) can be matched back from status webhooks.
            wamid = whatsapp.wamid_of(resp)
            if wamid:
                st = store.get_conversation(phone)
                for m in reversed(st.get("messages", [])):
                    if m.get("role") == "assistant":
                        m["wamid"] = wamid
                        m["delivery"] = "sent"  # upgrades to delivered/read via status webhook
                        break
                store.save_conversation(phone, st)
                store.set_wamid(wamid, phone)
            logger.info("Reply to %s: %s", phone, reply[:100])
        else:
            logger.info("Human mode for %s — message stored, no auto-reply", phone)
    except Exception as e:
        import traceback
        logger.error("Error processing message from %s: %s\n%s", phone, repr(e), traceback.format_exc())
        await whatsapp.send_message(
            phone,
            "Pedimos desculpa, ocorreu um erro. Por favor tente novamente. / Sorry, an error occurred. Please try again.",
        )

    return {"status": "ok"}


# ─── Admin Dashboard ─────────────────────────────────────────────────

ADMIN_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, system-ui, sans-serif; background: #f5f5f5; color: #333; }
.header { background: #2d6a4f; color: white; padding: 16px 30px; display: flex; align-items: center; gap: 16px; }
.header h1 { font-size: 20px; }
.header .logo { background: white; border-radius: 8px; padding: 6px 10px; display: flex; align-items: center; }
.header .logo img { height: 28px; display: block; }
.container { max-width: 900px; margin: 20px auto; padding: 0 20px; }
.badge { background: #e74c3c; color: white; padding: 3px 10px; border-radius: 12px; font-size: 13px; margin-left: 8px; }
.tabs { display: flex; gap: 8px; margin: 18px 0; flex-wrap: wrap; }
.tab { text-decoration: none; color: #555; background: white; border: 1px solid #ddd; padding: 8px 16px; border-radius: 20px; font-size: 14px; display: inline-flex; align-items: center; gap: 6px; }
.tab:hover { border-color: #2d6a4f; color: #2d6a4f; }
.tab-active { background: #2d6a4f; color: white; border-color: #2d6a4f; }
.tab-count { background: rgba(0,0,0,0.12); padding: 1px 8px; border-radius: 10px; font-size: 12px; }
.tab-active .tab-count { background: rgba(255,255,255,0.25); }
.card { background: white; border-radius: 10px; padding: 18px; margin: 12px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.1); cursor: pointer; transition: box-shadow 0.2s; display: block; text-decoration: none; color: inherit; }
.card:hover { box-shadow: 0 3px 10px rgba(0,0,0,0.15); }
.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.card-phone { font-weight: 600; font-size: 16px; color: #2d6a4f; }
.card-count { background: #e8f5e9; color: #2d6a4f; padding: 2px 10px; border-radius: 10px; font-size: 12px; }
.card-summary { color: #666; font-size: 14px; }
.priority-high { border-left: 4px solid #e74c3c; }
.priority-medium { border-left: 4px solid #f39c12; }
.priority-low { border-left: 4px solid #3498db; }
.empty { text-align: center; color: #888; padding: 60px 20px; }
.empty-icon { font-size: 48px; margin-bottom: 10px; }
.chat-box { background: white; border-radius: 10px; padding: 15px; max-height: 500px; overflow-y: auto; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
.msg { padding: 10px 14px; margin: 6px 0; border-radius: 10px; max-width: 85%; font-size: 14px; line-height: 1.5; }
.msg-customer { background: #dcf8c6; margin-right: auto; }
.msg-agent { background: #e3f2fd; margin-right: auto; }
.msg-human { background: #fff3e0; margin-left: auto; text-align: right; }
.msg-label { font-size: 11px; font-weight: 600; color: #888; margin-bottom: 3px; }
.fail-banner { background: #e74c3c; color: white; font-size: 12px; font-weight: 600; padding: 6px 10px; border-radius: 8px 8px 0 0; margin: -18px -18px 10px; }
.msg-time { font-weight: 400; color: #aaa; margin-left: 6px; }
.reply-form { margin-top: 15px; }
.reply-form textarea { width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 14px; font-family: inherit; resize: vertical; }
.btn { padding: 10px 24px; border: none; border-radius: 8px; font-size: 14px; cursor: pointer; font-weight: 500; }
.btn-send { background: #2d6a4f; color: white; }
.btn-send:hover { background: #1b4332; }
.btn-new { background: #2d6a4f; color: white; text-decoration: none; padding: 8px 16px; border-radius: 20px; font-size: 14px; display: inline-flex; align-items: center; gap: 6px; }
.btn-new:hover { background: #1b4332; }
.form-page { background: white; border-radius: 10px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
.form-page label { display: block; font-size: 13px; font-weight: 600; color: #555; margin: 14px 0 6px; }
.form-page input, .form-page textarea { width: 100%; padding: 10px 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 14px; font-family: inherit; }
.form-page textarea { resize: vertical; }
.form-hint { font-size: 12px; color: #888; margin-top: 4px; }
.error-box { background: #fde8e8; color: #c0392b; padding: 12px 15px; border-radius: 8px; margin-bottom: 15px; font-size: 14px; }
.btn-handback { background: #e67e22; color: white; }
.btn-handback:hover { background: #ca6f1e; }
.btn-delete { background: #c0392b; color: white; }
.btn-delete:hover { background: #96281b; }
.btn-row { margin-top: 10px; display: flex; gap: 10px; }
.back-link { display: inline-block; margin-bottom: 15px; color: #2d6a4f; text-decoration: none; font-size: 14px; }
.back-link:hover { text-decoration: underline; }
.status-badge { display: inline-block; padding: 3px 10px; border-radius: 10px; font-size: 12px; font-weight: 500; }
.status-human { background: #fde8e8; color: #e74c3c; }
.status-agent { background: #e8f5e9; color: #2d6a4f; }
.info-bar { background: #fff8e1; padding: 10px 15px; border-radius: 8px; margin-bottom: 15px; font-size: 13px; color: #666; }
.login-box { max-width: 380px; margin: 100px auto; background: white; padding: 30px; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
.login-box h2 { color: #2d6a4f; margin-bottom: 20px; }
.login-box input { width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 15px; margin-bottom: 12px; }
.login-box button { width: 100%; padding: 12px; background: #2d6a4f; color: white; border: none; border-radius: 8px; font-size: 15px; cursor: pointer; }
.login-box button:hover { background: #1b4332; }
.refresh-note { text-align: center; color: #aaa; font-size: 11px; margin-top: 20px; }
.stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin: 16px 0 22px; }
.stat-tile { background: white; border-radius: 10px; padding: 16px 18px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
.stat-tile .stat-value { font-size: 26px; font-weight: 700; color: #2d6a4f; line-height: 1.2; }
.stat-tile .stat-label { font-size: 13px; color: #666; margin-top: 4px; }
.period-bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 4px; }
.period-form { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.period-form input[type=date] { padding: 7px 10px; border: 1px solid #ddd; border-radius: 8px; font-size: 13px; font-family: inherit; }
.section-title { font-size: 15px; font-weight: 600; color: #333; margin: 22px 0 8px; }
.case-row { display: flex; justify-content: space-between; gap: 10px; padding: 10px 0; border-bottom: 1px solid #eee; font-size: 14px; }
.case-row:last-child { border-bottom: none; }
.case-summary { color: #666; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
"""


LOGO_URL = "https://fabricacoffeeroasters.com/cdn/shop/files/logo_fabrica.svg?v=1757331139&width=600"
LOGO_HTML = f'<span class="logo"><img src="{LOGO_URL}" alt="Fábrica Coffee Roasters"></span>'

from datetime import datetime, timezone, timedelta
try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Europe/Lisbon")
except Exception:
    _TZ = timezone.utc


def _delivery_badge(msg: dict) -> str:
    """Small WhatsApp-style delivery indicator for an outbound message."""
    d = msg.get("delivery", "")
    if not d:
        return ""
    if d == "read":
        return '<span title="Read by customer" style="color:#34b7f1;font-weight:400">✓✓</span>'
    if d == "delivered":
        return '<span title="Delivered to customer" style="color:#999;font-weight:400">✓✓</span>'
    if d == "sent":
        return '<span title="Sent — not yet confirmed delivered" style="color:#8a8a8a;font-weight:400">✓</span>'
    if d == "failed":
        return '<span title="NOT delivered by WhatsApp" style="color:#e74c3c;font-weight:600">&#9888; not delivered</span>'
    return ""


def _fmt_ts(iso: str, with_date: bool = True) -> str:
    """Format an ISO-UTC timestamp as Lisbon local time for display."""
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(_TZ)
        return dt.strftime("%d %b %Y, %H:%M" if with_date else "%H:%M")
    except Exception:
        return ""


def _check_auth(request: Request):
    token = request.cookies.get("admin_token")
    if token != settings.admin_password:
        raise HTTPException(status_code=401)


@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page():
    return f"""<!DOCTYPE html><html><head><title>Admin Login</title>
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <style>{ADMIN_CSS}</style></head>
    <body><div class="login-box"><h2>Fabrica Support</h2>
    <form method="post" action="/admin/login">
    <input type="password" name="password" placeholder="Password" required>
    <button type="submit">Login</button></form></div></body></html>"""


@app.post("/admin/login")
async def admin_login(password: str = Form()):
    if password != settings.admin_password:
        return HTMLResponse(
            f"""<!DOCTYPE html><html><head><style>{ADMIN_CSS}</style></head><body>
            <div class="login-box"><h2>Fabrica Support</h2><p style="color:#e74c3c;margin-bottom:12px">Wrong password</p>
            <form method="post" action="/admin/login">
            <input type="password" name="password" placeholder="Password" required>
            <button type="submit">Try again</button></form></div></body></html>""",
            status_code=401,
        )
    response = RedirectResponse("/admin", status_code=302)
    response.set_cookie("admin_token", password, httponly=True, max_age=86400, samesite="lax")
    return response


@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request, tab: str = "all", q: str = ""):
    try:
        _check_auth(request)
    except HTTPException:
        return RedirectResponse("/admin/login")

    all_convs = store.list_all()
    escalated_count = sum(1 for c in all_convs if c["mode"] == "human")
    whatsapp_count = sum(1 for c in all_convs if c.get("channel", "whatsapp") == "whatsapp")
    email_count = sum(1 for c in all_convs if c.get("channel") == "email")

    if tab == "human":
        conversations = [c for c in all_convs if c["mode"] == "human"]
    elif tab == "whatsapp":
        conversations = [c for c in all_convs if c.get("channel", "whatsapp") == "whatsapp"]
    elif tab == "email":
        conversations = [c for c in all_convs if c.get("channel") == "email"]
    else:
        tab = "all"
        conversations = all_convs

    # Free-text search across name, phone/email, subject and last message.
    ql = q.strip().lower()
    if ql:
        conversations = [
            c for c in conversations
            if ql in " ".join([
                c.get("name", ""), c.get("phone", ""),
                c.get("subject", ""), c.get("last_customer_text", ""),
            ]).lower()
        ]

    def _tab(key, label, count):
        active = "tab-active" if tab == key else ""
        qs = f"&q={html.escape(q, quote=True)}" if q else ""
        return f'<a href="/admin?tab={key}{qs}" class="tab {active}">{label} <span class="tab-count">{count}</span></a>'

    tabs_html = (
        '<div class="tabs" style="justify-content:space-between">'
        '<div style="display:flex;gap:8px;flex-wrap:wrap">'
        + _tab("all", "All", len(all_convs))
        + _tab("human", "Needs human", escalated_count)
        + _tab("whatsapp", "\U0001F4AC WhatsApp", whatsapp_count)
        + _tab("email", "✉️ Email", email_count)
        + '</div>'
        + '<div style="display:flex;gap:8px">'
        + '<a href="/admin/problems" class="tab">&#9888; Problems</a>'
        + '<a href="/admin/analytics" class="tab">&#128202; Analytics</a>'
        + '<a href="/admin/new" class="btn-new">+ New conversation</a>'
        + '</div>'
        + "</div>"
    )

    search_html = (
        f'<form method="get" action="/admin" style="margin:0 0 14px">'
        f'<input type="hidden" name="tab" value="{tab}">'
        f'<input type="text" name="q" value="{html.escape(q, quote=True)}" placeholder="Search name, phone, email or subject…" '
        f'style="width:100%;padding:11px 14px;border:1px solid #ddd;border-radius:10px;font-size:14px;box-sizing:border-box">'
        + ('<div style="font-size:12px;color:#888;margin-top:6px">Showing results for '
           f'"<strong>{html.escape(q)}</strong>" — <a href="/admin?tab={tab}" style="color:#2d6a4f">clear</a></div>' if q else '')
        + '</form>'
    )

    cards = ""
    for conv in conversations:
        phone = conv["phone"]
        count = conv["message_count"]
        is_human = conv["mode"] == "human"
        last_text = (conv.get("last_customer_text") or "")[:90]
        priority = "priority-high" if is_human else "priority-low"

        if is_human:
            tag = '<span class="status-badge status-human">Needs human</span>'
            detail = conv["summary"][:120] or "Escalated — awaiting team reply"
        else:
            tag = '<span class="status-badge status-agent">Bea handling</span>'
            detail = "Bea is handling this conversation automatically."

        display_name = html.escape(conv.get("name") or "Unknown name")
        channel = conv.get("channel", "whatsapp")
        chan_icon = "✉️" if channel == "email" else "\U0001F4AC"
        subject_html = ""
        if channel == "email" and conv.get("subject"):
            subject_html = f'<div style="margin-top:4px;font-size:12px;color:#555"><b>Subject:</b> {html.escape(conv["subject"][:90])}</div>'
        last_activity = _fmt_ts(conv.get("last_ts", ""))
        activity_html = f'<div style="margin-top:4px;font-size:12px;color:#aaa">Last activity: {last_activity}</div>' if last_activity else ""
        failed_banner = ('<div class="fail-banner">&#9888; Last reply was NOT delivered to the customer — please resend</div>'
                         if conv.get("last_delivery") == "failed" else "")
        cards += f"""<a href="/admin/chat/{html.escape(phone)}" class="card {priority}">
            {failed_banner}
            <div class="card-header">
                <span class="card-phone">{chan_icon} {display_name} &nbsp;<span style="color:#999;font-weight:400;font-size:13px">{html.escape(phone)}</span></span>
                <span>{tag} &nbsp; <span class="card-count">{count} msgs</span></span>
            </div>
            {subject_html}
            <div class="card-summary">{html.escape(detail)}</div>
            {'<div style="margin-top:6px;font-size:12px;color:#999">Last from customer: ' + html.escape(last_text) + '</div>' if last_text else ''}
            {activity_html}
        </a>"""

    if not cards:
        if q:
            empty_msg = f'No conversations match "{html.escape(q)}".'
        elif tab == "human":
            empty_msg = "No conversations need human attention — Bea has it covered."
        else:
            empty_msg = "No conversations yet"
        cards = f'<div class="empty"><div class="empty-icon">&#9745;</div><p>{empty_msg}</p></div>'

    return f"""<!DOCTYPE html><html><head><title>Fabrica Support — Admin</title>
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <style>{ADMIN_CSS}</style>
    <script>
    // Refresh only when the tab is visible and the user isn't typing a search —
    // a background tab makes no Redis calls, keeping usage well within limits.
    setInterval(function(){{
        var a=document.activeElement;
        var typing = a && (a.tagName==='INPUT' || a.tagName==='TEXTAREA');
        if(document.visibilityState==='visible' && !typing){{ location.reload(); }}
    }}, 30000);
    </script>
    </head>
    <body>
    <div class="header">{LOGO_HTML}<h1>Fabrica Support — Admin</h1></div>
    <div class="container">
    {tabs_html}
    {search_html}
    {cards}
    <div class="refresh-note">Auto-refreshes every 15 seconds · Escalated chats shown first</div>
    </div></body></html>"""


def _parse_iso(ts: str):
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _customer_window_open(state: dict) -> bool:
    """Whether WhatsApp's 24h free-form messaging window is currently open —
    true only if the customer has messaged us within the last 24h. Sending a
    template does NOT open this window; only the customer replying does."""
    for msg in reversed(state.get("messages", [])):
        if msg.get("role") == "customer":
            ts = _parse_iso(msg.get("ts", ""))
            return bool(ts and (datetime.now(timezone.utc) - ts) < timedelta(hours=24))
    return False


@app.get("/admin/analytics", response_class=HTMLResponse)
async def admin_analytics(request: Request, period: str = "30", start: str = "", end: str = ""):
    try:
        _check_auth(request)
    except HTTPException:
        return RedirectResponse("/admin/login")

    now = datetime.now(timezone.utc)
    range_end = now
    range_start = now - timedelta(days=30)

    if period == "custom" and start and end:
        try:
            range_start = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
            # End date is inclusive of the whole day.
            range_end = datetime.fromisoformat(end).replace(tzinfo=timezone.utc) + timedelta(days=1)
        except ValueError:
            period = "30"
    if period != "custom":
        days = {"7": 7, "30": 30, "90": 90}.get(period, 30)
        period = str(days)
        range_end = now
        range_start = now - timedelta(days=days)

    all_convs = store.list_all()

    new_conversations = 0
    cases = []  # (ts, phone, name, summary)
    for conv in all_convs:
        created = _parse_iso(conv.get("created_ts", ""))
        if created and range_start <= created <= range_end:
            new_conversations += 1
        for esc in conv.get("escalations", []):
            ts = _parse_iso(esc.get("ts", ""))
            if ts and range_start <= ts <= range_end:
                cases.append((ts, conv["phone"], conv.get("name") or conv["phone"], esc.get("summary", "")))

    cases.sort(key=lambda c: c[0], reverse=True)
    total_cases = len(cases)
    days_span = max((range_end - range_start).total_seconds() / 86400, 1)
    avg_per_day = total_cases / days_span
    avg_per_week = avg_per_day * 7
    avg_per_month = avg_per_day * 30
    escalation_rate = (total_cases / new_conversations * 100) if new_conversations else 0

    def _tile(value, label):
        return f'<div class="stat-tile"><div class="stat-value">{value}</div><div class="stat-label">{label}</div></div>'

    stats_html = (
        '<div class="stat-grid">'
        + _tile(new_conversations, "New conversations in period")
        + _tile(total_cases, "Cases escalated to human")
        + _tile(f"{escalation_rate:.0f}%", "Escalation rate")
        + _tile(f"{avg_per_day:.1f}", "Avg. cases / day")
        + _tile(f"{avg_per_week:.1f}", "Avg. cases / week")
        + _tile(f"{avg_per_month:.1f}", "Avg. cases / month")
        + "</div>"
    )

    def _period_link(key, label):
        active = "tab-active" if period == key else ""
        return f'<a href="/admin/analytics?period={key}" class="tab {active}">{label}</a>'

    start_val = start if period == "custom" else (range_start.strftime("%Y-%m-%d"))
    end_val = end if period == "custom" else (now.strftime("%Y-%m-%d"))
    period_bar = f"""<div class="period-bar">
        {_period_link("7", "Last 7 days")}
        {_period_link("30", "Last 30 days")}
        {_period_link("90", "Last 90 days")}
        <form method="get" action="/admin/analytics" class="period-form">
            <input type="hidden" name="period" value="custom">
            <input type="date" name="start" value="{start_val}" required>
            <span style="color:#999">&#8594;</span>
            <input type="date" name="end" value="{end_val}" required>
            <button type="submit" class="btn btn-send" style="padding:7px 16px">Apply</button>
        </form>
    </div>"""

    if cases:
        rows = ""
        for ts, phone, name, summary in cases[:25]:
            rows += f"""<a href="/admin/chat/{phone}" class="case-row" style="text-decoration:none;color:inherit">
                <span style="min-width:130px;color:#999">{_fmt_ts(ts.isoformat())}</span>
                <span style="min-width:140px;font-weight:500">{name}</span>
                <span class="case-summary">{(summary or "No summary")[:100]}</span>
            </a>"""
        cases_html = f'<div class="chat-box" style="max-height:420px">{rows}</div>'
    else:
        cases_html = '<div class="empty"><div class="empty-icon">&#9745;</div><p>No cases escalated in this period.</p></div>'

    return f"""<!DOCTYPE html><html><head><title>Analytics — Fabrica Support</title>
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <style>{ADMIN_CSS}</style></head>
    <body>
    <div class="header">{LOGO_HTML}<h1>Fabrica Support — Analytics</h1></div>
    <div class="container">
    <a href="/admin" class="back-link">&#8592; Back to dashboard</a>
    {period_bar}
    {stats_html}
    <div class="section-title">Recent cases in period</div>
    {cases_html}
    </div></body></html>"""


@app.get("/admin/new", response_class=HTMLResponse)
async def admin_new_conversation_page(request: Request):
    try:
        _check_auth(request)
    except HTTPException:
        return RedirectResponse("/admin/login")

    template_configured = bool(settings.whatsapp_new_conversation_template)
    template_note = (
        f'<div class="form-hint">If the customer hasn\'t messaged us in the last 24h, WhatsApp requires opening with '
        f'the approved template "<strong>{settings.whatsapp_new_conversation_template}</strong>" '
        f'({settings.whatsapp_template_language}) — your message below can\'t be delivered until they reply to it '
        f'(WhatsApp rule: only the customer replying opens the window, sending the template does not). It\'s queued '
        f'automatically and sent the moment they reply. If they messaged us recently, your message goes out immediately instead.</div>'
        if template_configured else
        '<div class="error-box">No approved WhatsApp template is configured yet, so this can only message customers who '
        'contacted us in the last 24 hours (free-form messages are rejected otherwise). Ask Claude to help set up a '
        'template in Meta Business Manager to enable true cold-start conversations.</div>'
    )

    return f"""<!DOCTYPE html><html><head><title>New conversation — Fabrica Support</title>
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <style>{ADMIN_CSS}</style></head>
    <body>
    <div class="header">{LOGO_HTML}<h1>Fabrica Support — Admin</h1></div>
    <div class="container">
    <a href="/admin" class="back-link">&#8592; Back to dashboard</a>
    <div class="form-page">
    <h2 style="color:#2d6a4f;margin-bottom:4px">Start a new conversation</h2>
    <p style="color:#666;font-size:14px">Send the first WhatsApp message to a customer. Bea will handle their replies automatically from then on.</p>
    {template_note}
    <form method="post" action="/admin/new">
        <label for="phone">Phone number</label>
        <input type="text" id="phone" name="phone" placeholder="e.g. 351912345678 (country code, no + or spaces)" required>
        <label for="name">Customer name (optional)</label>
        <input type="text" id="name" name="name" placeholder="e.g. Maria Silva">
        <label for="message">Message</label>
        <textarea id="message" name="message" rows="4" placeholder="Type the first message to send..." required></textarea>
        <div class="btn-row">
            <button type="submit" class="btn btn-send">Start conversation</button>
        </div>
    </form>
    </div>
    </div></body></html>"""


@app.post("/admin/new")
async def admin_new_conversation_send(
    request: Request,
    phone: str = Form(),
    message: str = Form(),
    name: str = Form(""),
):
    try:
        _check_auth(request)
    except HTTPException:
        return RedirectResponse("/admin/login")

    clean_phone = "".join(ch for ch in phone if ch.isdigit())

    if not clean_phone:
        return HTMLResponse(
            f"""<!DOCTYPE html><html><head><style>{ADMIN_CSS}</style></head><body>
            <div class="container"><div class="error-box">Please enter a valid phone number (digits only, with country code).</div>
            <a href="/admin/new" class="back-link">&#8592; Back</a></div></body></html>""",
            status_code=400,
        )

    template_configured = bool(settings.whatsapp_new_conversation_template)

    if name:
        store.set_customer_name(clean_phone, name)

    state = store.get_conversation(clean_phone)
    window_open = _customer_window_open(state)

    try:
        if window_open:
            # The customer messaged us within the last 24h, so the free-form
            # window is already open — send directly, no template needed.
            await whatsapp.send_message(clean_phone, message)
            state["messages"].append({"role": "human", "text": message, "ts": store.now_iso()})
        elif template_configured:
            # Outside the window: WhatsApp requires opening with an approved
            # template. Sending a template does NOT itself open the free-form
            # window though — only the customer replying does — so a
            # free-form follow-up sent right after would be silently
            # accepted by the API and then fail to deliver. Instead, queue
            # the admin's message and flush it for real once their reply
            # arrives (see receive_message in the webhook handler).
            await whatsapp.send_template_message(
                clean_phone,
                settings.whatsapp_new_conversation_template,
                settings.whatsapp_template_language,
            )
            state["pending_first_message"] = message
        else:
            # No template configured and outside the window — this will be
            # rejected by WhatsApp; surfaced to the admin as an error below.
            await whatsapp.send_message(clean_phone, message)
            state["messages"].append({"role": "human", "text": message, "ts": store.now_iso()})
    except Exception as e:
        logger.error("Failed to start conversation with %s: %s", clean_phone, e)
        if not window_open and template_configured:
            detail = (
                "Could not send the opening template message. Double-check the template name/language in .env "
                "match what was approved in Meta Business Manager."
            )
        elif not window_open:
            detail = (
                "Could not send the message via WhatsApp. This usually means the customer hasn't messaged us in the "
                "last 24 hours, so WhatsApp requires an approved message template to start the conversation instead "
                "of a free-form message."
            )
        else:
            detail = "Could not send the message via WhatsApp. Double-check the phone number and try again."
        return HTMLResponse(
            f"""<!DOCTYPE html><html><head><style>{ADMIN_CSS}</style></head><body>
            <div class="container">
            <div class="error-box">{detail}<br><br><strong>Details:</strong> {e}</div>
            <a href="/admin/new" class="back-link">&#8592; Back</a></div></body></html>""",
            status_code=502,
        )

    # A human started this conversation, so keep it in HUMAN mode — Bea must
    # not jump in. The team handles it; they can "Hand back to Agent" later if
    # they want Bea to take over.
    state["mode"] = "human"
    store.save_conversation(clean_phone, state)

    logger.info("Admin started new conversation with %s (window_open=%s)", clean_phone, window_open)
    return RedirectResponse(f"/admin/chat/{clean_phone}", status_code=302)


@app.get("/admin/chat/{phone}", response_class=HTMLResponse)
async def admin_chat_page(phone: str, request: Request, edit: int = None, send_error: int = 0):
    try:
        _check_auth(request)
    except HTTPException:
        return RedirectResponse("/admin/login")

    state = store.get_conversation(phone)
    messages = state.get("messages", [])
    mode = state.get("mode", "agent")
    customer_name = state.get("customer_name", "") or "Unknown name"

    chat_html = ""
    for i, msg in enumerate(messages):
        ts = _fmt_ts(msg.get("ts", ""))
        ts_html = f'<span class="msg-time">{ts}</span>' if ts else ""
        if msg.get("role") == "customer":
            caption_html = html.escape(msg["text"]) if msg.get("text") else ""
            media = msg.get("media")
            photo_html = ""
            if media and media.get("data"):
                photo_html = (
                    f'<div style="margin-top:{"6px" if caption_html else "0"}">'
                    f'<img src="data:{html.escape(media.get("mime_type", "image/jpeg"))};base64,{media["data"]}" '
                    f'style="max-width:280px;max-height:280px;border-radius:8px;display:block"></div>'
                )
            elif media:
                photo_html = '<div style="margin-top:6px;color:#999;font-size:12px">&#128247; Photo unavailable</div>'
            chat_html += f'<div class="msg msg-customer"><div class="msg-label">Customer {ts_html}</div>{caption_html}{photo_html}</div>'
        elif msg.get("role") == "assistant":
            content = msg.get("content", [])
            deliv = _delivery_badge(msg)
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = html.escape(block["text"]).replace("\n", "<br>")
                    chat_html += f'<div class="msg msg-agent"><div class="msg-label">Bea (AI) {ts_html} {deliv}</div>{text}</div>'
        elif msg.get("role") == "human":
            if edit == i:
                chat_html += f"""<div class="msg msg-human">
                    <div class="msg-label">You (Team) {ts_html}</div>
                    <form method="post" action="/admin/chat/{phone}/edit/{i}" style="text-align:left">
                        <textarea name="message" rows="3" style="width:100%;margin-top:4px" required>{html.escape(msg["text"])}</textarea>
                        <div class="btn-row" style="margin-top:6px;justify-content:flex-end">
                            <a href="/admin/chat/{phone}" class="tab" style="padding:6px 14px">Cancel</a>
                            <button type="submit" class="btn btn-send" style="padding:6px 16px">Save</button>
                        </div>
                    </form>
                </div>"""
            else:
                chat_html += f'<div class="msg msg-human"><div class="msg-label">You (Team) {ts_html} {_delivery_badge(msg)} &nbsp;<a href="/admin/chat/{phone}?edit={i}" style="font-weight:400;color:#999" title="Corrects the saved record only — does not change the message already delivered on WhatsApp">edit</a></div>{html.escape(msg["text"])}</div>'

    mode_badge = '<span class="status-badge status-human">Human mode</span>' if mode == "human" else '<span class="status-badge status-agent">Agent mode</span>'

    return f"""<!DOCTYPE html><html><head><title>Chat — {phone}</title>
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <style>{ADMIN_CSS}</style>
    <script>
    window.onload=function(){{var c=document.getElementById('chatbox');if(c)c.scrollTop=c.scrollHeight;}};
    // Auto-refresh for new messages, but NEVER while the team is typing a reply,
    // and only when the tab is visible (keeps Redis usage low).
    setInterval(function(){{
        var t=document.getElementById('reply');
        var typing = t && (t.value.trim().length>0 || document.activeElement===t);
        if(!typing && document.visibilityState==='visible'){{ location.reload(); }}
    }}, 15000);
    </script>
    </head>
    <body>
    <div class="header">{LOGO_HTML}<h1>Fabrica Support — Chat</h1></div>
    <div class="container">
    <a href="/admin" class="back-link">&#8592; Back to dashboard</a>
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
        <div><strong style="font-size:17px">{customer_name}</strong> &nbsp;<span style="color:#999">{phone}</span> &nbsp; {mode_badge}</div>
    </div>
    <div class="info-bar">{('<strong>Case:</strong> ' + state.get('escalation_summary', '')) if mode == 'human' and state.get('escalation_summary') else ('You (the team) are handling this conversation — Bea is paused. Use “Hand back to Agent” to let Bea take over.' if mode == 'human' else 'Bea is currently handling this conversation. Sending a message below will take it over.')}</div>
    {'<div class="error-box">Could not send that message via WhatsApp. Please try again in a moment.</div>' if send_error else ''}
    {f'<div class="error-box" style="background:#fff8e1;border-color:#f0c14b;color:#7a5c00">&#9203; Queued — the customer hasn\'t replied yet, so this can\'t be delivered until they do (WhatsApp only opens the free-form window when they reply). It will be sent automatically the moment they message us: <br><br><em>{html.escape(state["pending_first_message"])}</em></div>' if state.get("pending_first_message") else ""}
    <div class="chat-box" id="chatbox">{chat_html or '<p style="color:#888;text-align:center">No messages yet</p>'}</div>
    <form method="post" action="/admin/chat/{phone}/send" class="reply-form">
        <textarea id="reply" name="message" rows="3" placeholder="Type your reply to the customer..." required></textarea>
        <div class="btn-row">
            <button type="submit" class="btn btn-send">Send to Customer</button>
        </div>
    </form>
    <div style="margin-top:15px;display:flex;gap:10px;flex-wrap:wrap">
        <form method="post" action="/admin/chat/{phone}/handback">
            <button type="submit" class="btn btn-handback">Hand back to Agent</button>
        </form>
        <form method="post" action="/admin/chat/{phone}/delete" onsubmit="return confirm('Delete this entire conversation? This cannot be undone.');">
            <button type="submit" class="btn btn-delete">Delete conversation</button>
        </form>
    </div>
    <div class="refresh-note">Auto-refreshes for new messages, but pauses while you are typing</div>
    </div></body></html>"""


@app.post("/admin/chat/{phone}/send")
async def admin_send_message(phone: str, request: Request, message: str = Form()):
    try:
        _check_auth(request)
    except HTTPException:
        return RedirectResponse("/admin/login")

    state = store.get_conversation(phone)

    # Email conversations: reply by email (SMTP), threaded to the last message.
    if state.get("channel") == "email":
        try:
            email_client.send_email_reply(
                phone,
                state.get("email_subject", "") or "Your message",
                message,
                in_reply_to=state.get("email_last_message_id", ""),
                references=state.get("email_references", ""),
            )
            state["messages"].append({"role": "human", "text": message, "ts": store.now_iso()})
        except Exception as e:
            logger.error("Failed to send email to %s: %s", phone, e)
            store.log_incident("send_failed", f"Email to {phone}: {e}")
            return RedirectResponse(f"/admin/chat/{phone}?send_error=1", status_code=302)
        state["mode"] = "human"
        store.save_conversation(phone, state)
        return RedirectResponse(f"/admin/chat/{phone}", status_code=302)

    window_open = _customer_window_open(state)
    template_configured = bool(settings.whatsapp_new_conversation_template)

    try:
        if window_open:
            resp = await whatsapp.send_message(phone, message)
            hmsg = {"role": "human", "text": message, "ts": store.now_iso()}
            wamid = whatsapp.wamid_of(resp)
            if wamid:
                hmsg["wamid"] = wamid
                hmsg["delivery"] = "sent"
                store.set_wamid(wamid, phone)
            state["messages"].append(hmsg)
        elif template_configured:
            # The customer's gone quiet 24h+ — a free-form send here would be
            # silently accepted by WhatsApp and then fail to deliver (only
            # the customer replying re-opens the window, not us messaging
            # them). Re-open with the template and queue this reply to go
            # out the moment they respond (flushed in receive_message).
            await whatsapp.send_template_message(
                phone,
                settings.whatsapp_new_conversation_template,
                settings.whatsapp_template_language,
            )
            state["pending_first_message"] = message
        else:
            await whatsapp.send_message(phone, message)
            state["messages"].append({"role": "human", "text": message, "ts": store.now_iso()})
    except Exception as e:
        logger.error("Failed to send WhatsApp to %s: %s", phone, e)
        store.log_incident("send_failed", f"WhatsApp to {phone}: {e}")
        store.save_conversation(phone, state)
        return RedirectResponse(f"/admin/chat/{phone}?send_error=1", status_code=302)

    # A team member replying takes the conversation over — Bea stops
    # auto-replying until it is handed back.
    state["mode"] = "human"
    store.save_conversation(phone, state)

    return RedirectResponse(f"/admin/chat/{phone}", status_code=302)


@app.post("/admin/chat/{phone}/edit/{idx}")
async def admin_edit_message(phone: str, idx: int, request: Request, message: str = Form()):
    try:
        _check_auth(request)
    except HTTPException:
        return RedirectResponse("/admin/login")

    state = store.get_conversation(phone)
    messages = state.get("messages", [])
    # Only team-authored messages can be edited, and only the saved record —
    # this does not retract or resend what was already delivered on WhatsApp.
    if 0 <= idx < len(messages) and messages[idx].get("role") == "human":
        messages[idx]["text"] = message
        store.save_conversation(phone, state)
    else:
        logger.warning("Rejected edit for %s message index %s (not a team message)", phone, idx)

    return RedirectResponse(f"/admin/chat/{phone}", status_code=302)


@app.post("/admin/chat/{phone}/handback")
async def admin_handback(phone: str, request: Request):
    try:
        _check_auth(request)
    except HTTPException:
        return RedirectResponse("/admin/login")

    state = store.get_conversation(phone)
    store.set_mode(phone, "agent")

    # Only ping WhatsApp customers that Bea is back; email needs no such notice.
    if state.get("channel") != "email":
        try:
            await whatsapp.send_message(
                phone,
                "O nosso assistente virtual esta de volta para ajuda-lo. / Our virtual assistant is back to help you.",
            )
        except Exception:
            pass

    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/chat/{phone}/delete")
async def admin_delete_conversation(phone: str, request: Request):
    try:
        _check_auth(request)
    except HTTPException:
        return RedirectResponse("/admin/login")

    store.delete_conversation(phone)
    logger.info("Conversation %s deleted by admin", phone)
    return RedirectResponse("/admin", status_code=302)


@app.api_route("/tasks/poll-email", methods=["GET", "POST"])
async def poll_email(request: Request, secret: str = Query("")):
    """Check the support mailbox for new emails and let Bea answer them.
    Secured by a shared secret so only our scheduler can trigger it."""
    if secret != settings.email_poll_secret:
        return Response(status_code=403)
    try:
        result = await email_service.process_new_emails()
        logger.info("Email poll: %s", result)
        return result
    except Exception as e:
        logger.exception("Email poll failed")
        store.log_incident("email_poll", str(e))
        return {"status": "error"}


@app.get("/admin/problems", response_class=HTMLResponse)
async def admin_problems(request: Request):
    try:
        _check_auth(request)
    except HTTPException:
        return RedirectResponse("/admin/login")

    all_convs = store.list_all()
    failed = [c for c in all_convs if c.get("last_delivery") == "failed"]
    incidents = store.get_incidents()

    # Undelivered-message conversations
    if failed:
        rows = ""
        for c in failed:
            name = html.escape(c.get("name") or c["phone"])
            rows += (f'<a href="/admin/chat/{html.escape(c["phone"])}" class="case-row" style="text-decoration:none;color:inherit">'
                     f'<span style="min-width:150px;font-weight:500">{name}</span>'
                     f'<span class="case-summary">Last reply not delivered — {html.escape((c.get("last_customer_text") or "")[:80])}</span>'
                     f'<span style="color:#e74c3c;font-weight:600">not delivered</span></a>')
        failed_html = f'<div class="chat-box" style="max-height:320px">{rows}</div>'
    else:
        failed_html = '<div class="empty"><div class="empty-icon">&#9745;</div><p>No undelivered messages.</p></div>'

    # Recent incidents log
    _labels = {"whatsapp_failed": "WhatsApp not delivered", "email_poll": "Email check failed",
               "send_failed": "Send failed", "health": "Health check"}
    if incidents:
        irows = ""
        for inc in incidents:
            label = _labels.get(inc.get("kind", ""), inc.get("kind", "issue"))
            irows += (f'<div class="case-row">'
                      f'<span style="min-width:150px;color:#999">{_fmt_ts(inc.get("ts", ""))}</span>'
                      f'<span style="min-width:150px;font-weight:500">{html.escape(label)}</span>'
                      f'<span class="case-summary">{html.escape(inc.get("detail", ""))}</span></div>')
        incidents_html = f'<div class="chat-box" style="max-height:360px">{irows}</div>'
    else:
        incidents_html = '<div class="empty"><div class="empty-icon">&#9745;</div><p>No incidents logged. All quiet.</p></div>'

    redis_ok = "✅ OK" if store.redis_healthy() else "❌ DOWN / over limit"

    return f"""<!DOCTYPE html><html><head><title>Problems — Fabrica Support</title>
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <meta http-equiv="refresh" content="30">
    <style>{ADMIN_CSS}</style></head>
    <body>
    <div class="header">{LOGO_HTML}<h1>Fabrica Support — Problems</h1></div>
    <div class="container">
    <a href="/admin" class="back-link">&#8592; Back to dashboard</a>
    <div class="info-bar">System status — Redis: <strong>{redis_ok}</strong></div>
    <div class="section-title">Undelivered messages ({len(failed)})</div>
    {failed_html}
    <div class="section-title">Recent incidents</div>
    {incidents_html}
    <div class="refresh-note">Auto-refreshes every 30 seconds</div>
    </div></body></html>"""


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/health/deep")
async def health_deep():
    """Deeper health check that verifies Redis is reachable and within limits.
    Point an uptime monitor here — it catches real outages (like the Redis
    request-limit exhaustion) that a plain 'server up' check would miss."""
    if not store.redis_healthy():
        store.log_incident("health", "Redis health check failed")
        return Response(content='{"status":"degraded","redis":false}',
                        media_type="application/json", status_code=503)
    return {"status": "healthy", "redis": True}
