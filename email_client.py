"""Support mailbox client — read incoming emails (IMAP) and send replies (SMTP).

Reads unseen messages from support@fabricacoffeeroasters.com, and sends replies
as support@ with correct threading headers so they stay in the same email thread.
Uses only the Python standard library (imaplib / smtplib / email).
"""

import imaplib
import smtplib
import email
from email.header import decode_header, make_header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.utils import parseaddr, formataddr, formatdate, make_msgid
from config import settings


SIGNATURE = (
    "\n\n—\n"
    "Fábrica Coffee Roasters\n"
    "support@fabricacoffeeroasters.com · +351 913 550 000"
)


def configured() -> bool:
    return bool(settings.support_email_address and settings.support_email_password)


def _decode(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _plain_body(msg: email.message.Message) -> str:
    """Extract a plain-text body from an email message."""
    if msg.is_multipart():
        # Prefer text/plain; fall back to stripped text/html.
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition", "")):
                try:
                    return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
                except Exception:
                    continue
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                try:
                    html = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
                    return _strip_html(html)
                except Exception:
                    continue
        return ""
    try:
        payload = msg.get_payload(decode=True)
        text = payload.decode(msg.get_content_charset() or "utf-8", "replace")
        return _strip_html(text) if msg.get_content_type() == "text/html" else text
    except Exception:
        return ""


def _strip_html(html: str) -> str:
    import re
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", html)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    from html import unescape
    return unescape(text).strip()


def _quote_trim(body: str) -> str:
    """Drop quoted history so Bea sees only the new message the customer wrote."""
    lines = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith(">"):
            break
        if stripped.startswith("On ") and stripped.endswith("wrote:"):
            break
        if stripped in ("--", "-- ") or stripped.startswith("________"):
            break
        lines.append(line)
    return "\n".join(lines).strip() or body.strip()


def fetch_new_emails(limit: int = 10) -> list[dict]:
    """Fetch unseen emails from the support inbox and mark them as seen.

    Returns a list of {from_email, from_name, subject, body, message_id,
    references, date}. Newest last.
    """
    results = []
    imap = imaplib.IMAP4_SSL(settings.support_imap_host, settings.support_imap_port)
    try:
        imap.login(settings.support_email_address, settings.support_email_password)
        imap.select("INBOX")
        status, data = imap.search(None, "UNSEEN")
        if status != "OK":
            return results
        ids = data[0].split()
        for msg_id in ids[:limit]:
            status, msg_data = imap.fetch(msg_id, "(RFC822)")
            if status != "OK" or not msg_data or not msg_data[0]:
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            from_name, from_email = parseaddr(msg.get("From", ""))
            body = _quote_trim(_plain_body(msg))
            results.append({
                "from_email": from_email.lower().strip(),
                "from_name": _decode(from_name),
                "subject": _decode(msg.get("Subject", "")),
                "body": body,
                "message_id": msg.get("Message-ID", "").strip(),
                "references": msg.get("References", "").strip(),
                "date": msg.get("Date", ""),
            })
            imap.store(msg_id, "+FLAGS", "\\Seen")
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    return results


def send_email_reply(to_email: str, subject: str, body: str,
                     in_reply_to: str = "", references: str = "",
                     attachments: list | None = None) -> str:
    """Send a reply from the support mailbox. Returns the new Message-ID.

    `attachments` is an optional list of (filename, bytes, mime_subtype) tuples.
    """
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}" if subject else "Re: Your message"

    # Append the support signature unless the body already includes it.
    if SIGNATURE.strip() not in body:
        body = body.rstrip() + SIGNATURE

    if attachments:
        msg = MIMEMultipart()
        msg.attach(MIMEText(body, "plain", "utf-8"))
        for fname, data, mimetype in attachments:
            sub = mimetype.split("/")[-1] if "/" in mimetype else mimetype
            part = MIMEApplication(data, _subtype=sub)
            part.add_header("Content-Disposition", "attachment", filename=fname)
            msg.attach(part)
    else:
        msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = formataddr(("Fábrica Coffee Roasters", settings.support_email_address))
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    new_id = make_msgid(domain="fabricacoffeeroasters.com")
    msg["Message-ID"] = new_id
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = (references + " " + in_reply_to).strip()

    with smtplib.SMTP(settings.support_smtp_host, settings.support_smtp_port, timeout=30) as server:
        server.starttls()
        server.login(settings.support_email_address, settings.support_email_password)
        server.send_message(msg)
    return new_id
