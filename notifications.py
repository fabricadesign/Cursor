"""Send escalation alerts to the team via email and WhatsApp."""

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config import settings
import whatsapp

logger = logging.getLogger(__name__)

DESK_WHATSAPP_FALLBACK = "+351912338809"


def _norm(n: str) -> str:
    return "".join(ch for ch in (n or "") if ch.isdigit())


async def send_escalation_alert(
    customer_phone: str,
    summary: str,
    customer_name: str = "Unknown",
    order_number: str = "",
):
    """Send escalation alert to team via email and WhatsApp.

    The inbox tag is flipped by the caller. This function is what actually
    pings the desk. A free-form WhatsApp to the desk dies with Graph 131047
    once 24 hours have passed since that number last messaged the WABA, so
    we try an approved template first.
    """
    subject = f"⚠️ Customer Escalation — {customer_name}"
    if order_number:
        subject += f" (Order {order_number})"

    body = (
        f"A customer issue needs human attention.\n\n"
        f"Customer phone: {customer_phone}\n"
        f"Customer name: {customer_name}\n"
        f"Order: {order_number or 'N/A'}\n\n"
        f"Summary:\n{summary}\n\n"
        f"Please follow up with the customer as soon as possible."
    )

    errors = []

    if settings.alert_email_to and settings.smtp_host:
        try:
            _send_email(subject, body)
        except Exception as e:
            errors.append(f"Email failed: {e}")

    alert_num = (settings.alert_whatsapp_number or DESK_WHATSAPP_FALLBACK).strip()
    if alert_num and settings.whatsapp_access_token and _norm(alert_num) != _norm(customer_phone):
        ping_errors = await _ping_desk_whatsapp(alert_num, f"{subject}\n\n{body}", summary)
        errors.extend(ping_errors)
    elif alert_num and _norm(alert_num) == _norm(customer_phone):
        errors.append("WhatsApp alert skipped: desk number is the customer's number")
    elif not settings.whatsapp_access_token:
        errors.append("WhatsApp alert skipped: missing access token")

    if errors:
        try:
            import store
            store.log_incident("whatsapp_alert", "; ".join(errors)[:300])
        except Exception:
            pass
        logger.warning("Escalation alert partial/failed: %s", errors)
        return {"status": "partial", "errors": errors}
    return {"status": "sent"}


async def _ping_desk_whatsapp(alert_num: str, body: str, summary: str) -> list[str]:
    """Template first (survives the 24h window), then a session text."""
    errors: list[str] = []
    template = (
        (settings.whatsapp_escalation_template or "").strip()
        or (settings.whatsapp_new_conversation_template or "").strip()
    )
    if template:
        try:
            await whatsapp.send_template_message(
                alert_num,
                template,
                settings.whatsapp_template_language,
                parameters=[(summary or "Human needed")[:320]],
            )
            return []
        except Exception as e:
            errors.append(f"WhatsApp template (with body) failed: {e}")
            logger.warning("Desk template ping with body failed: %s", e)
        try:
            await whatsapp.send_template_message(
                alert_num,
                template,
                settings.whatsapp_template_language,
            )
            return []
        except Exception as e:
            errors.append(f"WhatsApp template failed: {e}")
            logger.warning("Desk template ping failed, trying session text: %s", e)

    try:
        await whatsapp.send_message(alert_num, body[:4096])
        return []
    except Exception as e:
        errors.append(f"WhatsApp alert failed: {e}")
        return errors


def _send_email(subject: str, body: str):
    msg = MIMEMultipart()
    msg["From"] = settings.smtp_from or settings.alert_email_to
    msg["To"] = settings.alert_email_to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        if settings.smtp_port != 25:
            server.starttls()
        if settings.smtp_username and settings.smtp_password:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(msg)
