"""Output checks that run on Bea's draft before it is sent.

The playbook lists support@fabricacoffeeroasters.com as the public contact.
On WhatsApp that address is a bounce: the customer is already talking to
support. Strip those referrals unless they explicitly asked for the email.
"""

from __future__ import annotations

import re

SUPPORT_MAILBOXES = (
    "support@fabricacoffeeroasters.com",
    "orders@fabricacoffeeroasters.com",
    "b2b@fabricacoffeeroasters.com",
)

ASKS_CONTACT = re.compile(
    r"(?:outro canal|outros canais|qual (?:é )?o (?:e-?mail|telefone|whats)|"
    r"como (?:falo|entro em contacto|entro em contato)|canais de atendimento|"
    r"t[êe]m (?:e-?mail|telefone)|vosso e-?mail|seu e-?mail|"
    r"another channel|other channels|what'?s your (?:email|phone|number)|"
    r"how (?:can|do) i (?:contact|reach)|send me (?:your )?e-?mail)",
    re.I,
)

MAILBOX_RE = re.compile(
    r"\b(?:support|orders|b2b)@fabricacoffeeroasters\.com\b",
    re.I,
)

BOUNCE_RE = re.compile(
    r"(?:envie|encaminhe|escreva|contacte|contact|email|e-mail)"
    r"[^.!?\n]{0,90}"
    r"(?:support@|orders@|b2b@|o suporte|à equipa por e-?mail|our support e-?mail)",
    re.I,
)

_STAY = {
    "pt": (
        "Já está no sítio certo — podemos continuar aqui no WhatsApp. "
        "Qual é o número da encomenda ou o email da compra?"
    ),
    "en": (
        "You're already in the right place — we can continue here on WhatsApp. "
        "What's the order number or the email on the order?"
    ),
}


def should_agent_speak(channel: str, mode: str) -> bool:
    """Bea replies on WhatsApp in agent mode only."""
    if (channel or "whatsapp") == "email":
        return False
    if (mode or "agent") == "human":
        return False
    return True


def customer_asked_for_contact(text: str) -> bool:
    return bool(ASKS_CONTACT.search(text or ""))


def looks_like_portuguese(text: str) -> bool:
    return bool(
        re.search(
            r"[ãáàâçéêíóôõú]|(\b(olá|obrigad|encomenda|por favor|bom dia)\b)",
            text or "",
            re.I,
        )
    )


def _split_sentences(text: str) -> list[str]:
    """Split on . ! ? without cutting email addresses in half."""
    held: list[str] = []

    def stash(match: re.Match) -> str:
        held.append(match.group(0))
        return f"«M{len(held) - 1}»"

    masked = MAILBOX_RE.sub(stash, text)
    masked = re.sub(r"https?://\S+", stash, masked)
    parts = re.split(r"(?<=[.!?])\s+", masked)
    out = []
    for part in parts:
        for i, original in enumerate(held):
            part = part.replace(f"«M{i}»", original)
        if part.strip():
            out.append(part)
    return out


def drop_sentences(text: str, predicate) -> str:
    kept = [s for s in _split_sentences(text) if not predicate(s)]
    return " ".join(kept).strip()


def mentions_support_mailbox(text: str) -> bool:
    lower = (text or "").lower()
    return bool(MAILBOX_RE.search(text or "")) or any(m in lower for m in SUPPORT_MAILBOXES)


def scrub_support_mailbox_deflection(reply: str, customer_text: str) -> tuple[str, bool]:
    """Remove 'email support@…' bounces. Returns (text, repaired)."""
    if not reply:
        return reply, False
    if customer_asked_for_contact(customer_text):
        return reply, False

    def bounce(sentence: str) -> bool:
        return mentions_support_mailbox(sentence) or bool(BOUNCE_RE.search(sentence))

    if not bounce(reply):
        return reply, False

    cleaned = drop_sentences(reply, bounce)
    if not cleaned:
        lang = "pt" if looks_like_portuguese(customer_text or reply) else "en"
        cleaned = _STAY[lang]
    return cleaned, True
