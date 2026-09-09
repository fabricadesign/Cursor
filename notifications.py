"""Send escalation alerts to the team via email and WhatsApp."""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config import settings
import whatsapp


async def send_escalation_alert(
    customer_phone: str,
    summary: str,
    customer_name: str = "Unknown",
    order_number: str = "",
):
    """Send escalation alert to team via email and WhatsApp."""
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

    # Send email
    if settings.alert_email_to and settings.smtp_host:
        try:
            _send_email(subject, body)
        except Exception as e:
            errors.append(f"Email failed: {e}")

    # Send WhatsApp to team — but NEVER to the customer's own number
    def _norm(n: str) -> str:
        return "".join(ch for ch in (n or "") if ch.isdigit())

    alert_num = settings.alert_whatsapp_number
    if alert_num and settings.whatsapp_access_token and _norm(alert_num) != _norm(customer_phone):
        try:
            await whatsapp.send_message(alert_num, f"{subject}\n\n{body}")
        except Exception as e:
            errors.append(f"WhatsApp alert failed: {e}")

    if errors:
        return {"status": "partial", "errors": errors}
    return {"status": "sent"}


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
