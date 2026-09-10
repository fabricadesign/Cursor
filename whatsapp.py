"""WhatsApp Cloud API integration — webhook handler and message sender."""

import httpx
from config import settings

GRAPH_API = "https://graph.facebook.com/v21.0"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.whatsapp_access_token}",
        "Content-Type": "application/json",
    }


async def _post(payload: dict) -> dict:
    """POST to the messages endpoint, raising with Meta's actual error body
    on failure (httpx's default raise_for_status() message discards it)."""
    url = f"{GRAPH_API}/{settings.whatsapp_phone_number_id}/messages"
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json=payload, headers=_headers())
        if resp.status_code >= 400:
            raise RuntimeError(f"WhatsApp API error {resp.status_code}: {resp.text}")
        return resp.json()


async def send_message(to_phone: str, text: str):
    """Send a text message via WhatsApp Cloud API."""
    return await _post({
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "text",
        "text": {"body": text},
    })


async def send_template_message(to_phone: str, template_name: str, language_code: str, parameters: list[str] | None = None):
    """Send an approved WhatsApp message template — the only way to start a
    conversation with a customer who hasn't messaged us in the last 24h."""
    components = []
    if parameters:
        components.append({
            "type": "body",
            "parameters": [{"type": "text", "text": p} for p in parameters],
        })
    return await _post({
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language_code},
            "components": components,
        },
    })


async def send_document(to_phone: str, link: str, filename: str, caption: str = ""):
    """Send a document (e.g. invoice PDF) by URL."""
    url = f"{GRAPH_API}/{settings.whatsapp_phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "document",
        "document": {"link": link, "filename": filename, "caption": caption},
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload, headers=_headers())
        resp.raise_for_status()
        return resp.json()


async def mark_read_and_typing(message_id: str):
    """Mark an incoming message as read and show the typing indicator.

    The typing indicator is shown for up to 25 seconds or until we send a
    message — whichever comes first.
    """
    url = f"{GRAPH_API}/{settings.whatsapp_phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
        "typing_indicator": {"type": "text"},
    }
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, json=payload, headers=_headers())
            return resp.json()
        except Exception:
            return None


def wamid_of(resp: dict) -> str:
    """Pull the WhatsApp message id (wamid) out of a send response."""
    try:
        return (resp or {}).get("messages", [{}])[0].get("id", "")
    except (IndexError, AttributeError):
        return ""


def extract_statuses(webhook_body: dict) -> list[dict]:
    """Extract delivery-status events (sent/delivered/read/failed) from a webhook.

    These arrive separately from customer messages and tell us whether a
    message we sent actually reached the customer.
    """
    out = []
    try:
        value = webhook_body["entry"][0]["changes"][0]["value"]
    except (KeyError, IndexError):
        return out
    for st in value.get("statuses", []):
        errors = st.get("errors") or []
        title = ""
        code = None
        if errors:
            title = errors[0].get("title") or errors[0].get("message") or ""
            code = errors[0].get("code")
        error = f"{title} ({code})" if (title and code) else (title or (str(code) if code else ""))
        out.append({
            "id": st.get("id", ""),
            "status": st.get("status", ""),  # sent | delivered | read | failed
            "recipient": st.get("recipient_id", ""),
            "error": error,
            "error_code": code,
        })
    return out


def extract_message(webhook_body: dict) -> tuple[str, str, str, str, dict | None] | None:
    """Extract (phone_number, message_text, message_id, customer_name, media).

    `media` is a dict {"id", "mime_type"} when the customer sent a photo
    (`text` is then their caption, or "" if none), otherwise None.
    Returns None if the payload is not a user text or image message.
    """
    try:
        entry = webhook_body["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]
        message = value["messages"][0]
        phone = message["from"]
        message_id = message.get("id", "")

        media = None
        if message["type"] == "text":
            text = message["text"]["body"]
        elif message["type"] == "image":
            image = message.get("image", {})
            text = image.get("caption", "")
            media = {"id": image.get("id", ""), "mime_type": image.get("mime_type", "image/jpeg")}
        else:
            return None

        # Customer's WhatsApp profile name (if shared)
        name = ""
        try:
            name = value["contacts"][0]["profile"]["name"]
        except (KeyError, IndexError):
            pass
        return phone, text, message_id, name, media
    except (KeyError, IndexError):
        return None


async def get_media_url(media_id: str) -> tuple[str, str]:
    """Look up the short-lived download URL and mime type for a media object.

    The returned URL must be fetched with the same access token (see
    download_media) — it isn't a public link.
    """
    url = f"{GRAPH_API}/{media_id}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=_headers())
        resp.raise_for_status()
        data = resp.json()
        return data["url"], data.get("mime_type", "image/jpeg")


async def download_media(media_id: str) -> tuple[bytes, str]:
    """Download a media object's raw bytes and mime type.

    WhatsApp media URLs expire quickly, so this must be called promptly
    (i.e. right when the webhook arrives), not deferred.
    """
    media_url, mime_type = await get_media_url(media_id)
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(media_url, headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"})
        resp.raise_for_status()
        return resp.content, mime_type
