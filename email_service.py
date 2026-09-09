"""Email support pipeline: fetch new support emails, let Bea answer them, and
reply by email — mirroring the WhatsApp webhook flow but for the email channel.
"""

import logging
import email_client
import store
import agent

logger = logging.getLogger(__name__)

# Never auto-reply to these senders (avoids mail loops / replying to robots).
_SKIP_SENDER_MARKERS = (
    "no-reply", "noreply", "no_reply", "donotreply", "do-not-reply",
    "mailer-daemon", "postmaster", "mailerdaemon", "bounce",
)
_SKIP_SUBJECT_MARKERS = (
    "out of office", "automatic reply", "auto-reply", "delivery status notification",
    "undeliverable", "mail delivery failed",
)


def _should_skip(sender: str, subject: str) -> bool:
    s = (sender or "").lower()
    if not s or "@" not in s:
        return True
    if s == store_support_address():
        return True
    if any(m in s for m in _SKIP_SENDER_MARKERS):
        return True
    subj = (subject or "").lower()
    if any(m in subj for m in _SKIP_SUBJECT_MARKERS):
        return True
    return False


def store_support_address() -> str:
    from config import settings
    return (settings.support_email_address or "").lower()


async def process_new_emails(limit: int = 10) -> dict:
    """Fetch unseen support emails, have Bea answer each, and reply by email.

    Returns a small summary for logging/monitoring.
    """
    if not email_client.configured():
        return {"status": "email_not_configured"}

    emails = email_client.fetch_new_emails(limit=limit)
    processed, skipped, replied, human = 0, 0, 0, 0

    for mail in emails:
        sender = mail["from_email"]
        if _should_skip(sender, mail["subject"]):
            skipped += 1
            continue
        processed += 1

        # EMAIL IS HUMAN-ONLY: Bea never auto-replies to email. We just store the
        # incoming message as an email conversation in HUMAN mode, so it shows in
        # the dashboard (Email tab + Needs human) for the team to reply to.
        state = store.get_conversation(sender)
        state["channel"] = "email"
        state["mode"] = "human"
        if mail.get("from_name"):
            state["customer_name"] = mail["from_name"]
        if not state.get("email_subject"):
            state["email_subject"] = mail["subject"]
        state["email_last_message_id"] = mail["message_id"]
        state["email_references"] = mail["references"]
        if not state.get("escalation_summary"):
            state["escalation_summary"] = f"Email: {mail['subject'] or '(no subject)'}"
        state["messages"].append({
            "role": "customer",
            "text": mail["body"] or "(no message body)",
            "ts": store.now_iso(),
        })
        store.save_conversation(sender, state)
        human += 1

    return {
        "status": "ok",
        "fetched": len(emails),
        "processed": processed,
        "skipped": skipped,
        "stored_for_team": human,
    }
