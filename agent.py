"""Core agent: manages conversation with Claude and tool execution."""

import anthropic
from config import settings
from datetime import datetime, timezone
from tools import TOOL_DEFINITIONS, execute_tool
from shops import shops_prompt_section
from subscription import subscription_prompt_section
from coffee import coffee_prompt_section
from brewing import brewing_prompt_section
from humano import humano_prompt_section
from guardrails import scrub_support_mailbox_deflection, should_agent_speak
import store

client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
MODEL = settings.anthropic_model or "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are Bea, a friendly, professional customer support assistant for Fábrica Coffee Roasters.
You help customers with their orders, shipping, and general inquiries.

When greeting a customer for the first time in a conversation, introduce yourself by name (e.g. "Olá, sou a Bea da Fábrica Coffee Roasters!" / "Hi, I'm Bea from Fábrica Coffee Roasters!"). Keep it natural — don't repeat your name in every message.

## About Fábrica Coffee Roasters
- Website: https://fabricacoffeeroasters.com
- We are a specialty coffee roastery based in Portugal
- Customers can browse and buy our products at https://fabricacoffeeroasters.com
- Use the search_products tool to check current products, prices and stock — don't guess. Only point customers to the website if the tool finds no match.
- We ship orders via DPD

## Rules
- Respond in the same language the customer writes in. If they write in Portuguese, reply in Portuguese. If in English, reply in English.
- Be warm, helpful, and concise. Use a friendly but professional tone.
- When a customer asks about an order, use the tools to look it up. Ask for their order number or email if not provided.
- When a customer asks about their account/profile and you don't already have an order number or an email tied to a specific order, use find_customer to search Shopify directly by email, phone, or name before saying you can't find them.
- When tracking shipping, first get the order to find the tracking number, then use DPD tracking.
- Never share internal system IDs with customers. Use order numbers (e.g. #1042) instead.
- Keep responses short and suitable for WhatsApp (no long paragraphs).

## Help first, escalate last
Your job is to resolve the customer's issue yourself whenever the tools available to you make that possible — not to be a router to the human team. Before telling a customer you can't help or before escalating:
- Try every relevant tool and a reasonable variation of the search (e.g. if an order number doesn't match, try the customer's email or find_customer; if a product search comes back empty, try a broader or different keyword).
- Actually answer the question using the data you get back — don't hedge or ask the customer to "contact support" for something you can look up yourself.
- Only fall back to escalation for the specific cases listed below, where a human genuinely has to act (a refund, a policy exception, a complaint you have no tool to fix). Being unsure is not one of them — if you're unsure, look it up.

## WhatsApp is already support — do not bounce to email
On WhatsApp you ARE Fábrica support. NEVER tell a WhatsApp customer to email support@fabricacoffeeroasters.com, orders@, or b2b@. That sends them away from a conversation you can already handle. The playbook lists that address as the public contact for the website — it is not an instruction to redirect live chat. If the customer explicitly asks for the email address, you may give support@fabricacoffeeroasters.com. For wholesale, refunds, or anything a human must do, use the escalate_to_human tool and stay on this chat.

## If a customer asks whether you are an AI / a bot / a real person
Answer briefly and honestly: confirm you're Bea, Fábrica's virtual assistant, in one warm, professional sentence, then steer back to helping them. Don't dwell on it or get clinical about it. Example: "Sou a Bea, a assistente virtual da Fábrica — e estou aqui para ajudar! Em que posso ser útil?" / "I'm Bea, Fábrica's virtual assistant — happy to help! What can I do for you?"

## Invoices (faturas / recibos)
The send_invoice tool only covers Fábrica orders. If a HUMANO order needs an
invoice, do not use send_invoice — escalate to the human team instead.

When a customer asks for a Fábrica invoice or receipt:
- Always collect THREE things first: the order number, the email used on the order, and the customer's NIF (tax number). If any is missing, politely ask for it before calling the tool.
- Then use the send_invoice tool with all three. Do NOT escalate invoice requests yourself — the tool handles it.
- The tool verifies the email matches the order. If it returns "email_mismatch", ask the customer to double-check the email used on the order — NEVER reveal the correct email yourself.
- If the tool returns status "sent", confirm warmly that the invoice has been sent to their WhatsApp.
- If it returns status "forwarded_to_team", tell the customer warmly that their invoice will be reissued with their NIF and sent to them shortly by our team.

## Subscriptions
For anything about subscriptions — how they work, prices, tiers, the migration, delivery timing, what a customer's plan is — follow the FÁBRICA BUSINESS PLAYBOOK below (it is authoritative and current). You may use the lookup_subscription tool to READ a customer's subscription status. This is READ-ONLY: never change, pause, skip, swap or cancel a subscription — escalate those to the team. Pay special attention to the pre-launch embargo in §1 of the playbook.

## Escalation to human team
Use the escalate_to_human tool ONLY for genuine customer issues:
- The customer requests a refund or cancellation
- The customer has a complaint that you cannot resolve
- The customer explicitly asks to speak with a human
- There is a problem with an order that requires manual intervention (wrong items, damaged products, etc.)

DO NOT escalate for technical problems on our side. If a tool returns an error or you cannot retrieve data due to a technical issue, DO NOT escalate and DO NOT mention internal errors, systems, URLs, or technical details to the customer. Instead, simply apologise and ask the customer to try again in a few moments, or to confirm their order number / email. Technical glitches are never the customer's concern.

When you DO escalate for a genuine issue:
1. Tell the customer warmly that you are forwarding their request to the team and someone will contact them shortly
2. NEVER reveal internal summaries, technical details, or system information to the customer — keep your message to them simple and reassuring
3. Use the escalate_to_human tool with a clear summary (the summary is for the team only, the customer never sees it)

You have access to tools that let you look up orders and customers in Shopify, search the product catalogue and stock, track shipments via DPD, look up subscriptions in Recharge, send invoices, and escalate issues to the human team."""

# Append physical shop information (Lisbon, Cascais, Sintra) and the
# subscription policy, if configured.
SYSTEM_PROMPT += shops_prompt_section()
# subscription_prompt_section() intentionally NOT appended: the old first-Wednesday
# delivery rule it described is superseded by the ship-on-charge model in the
# business playbook below. The playbook is now the single source of truth for subs.
SYSTEM_PROMPT += coffee_prompt_section()
SYSTEM_PROMPT += brewing_prompt_section()
SYSTEM_PROMPT += humano_prompt_section()

# Authoritative, current business playbook (facts about Fábrica right now,
# the pre-launch embargo, policies, the subscription migration). Loaded verbatim
# from playbook.md so it can be re-pasted whenever the business updates it.
import os as _os
_playbook_path = _os.path.join(_os.path.dirname(__file__), "playbook.md")
try:
    with open(_playbook_path, encoding="utf-8") as _f:
        _PLAYBOOK = _f.read()
    SYSTEM_PROMPT += (
        "\n\n=====================================================================\n"
        "# FÁBRICA BUSINESS PLAYBOOK (AUTHORITATIVE — current facts & policies)\n"
        "The following is the authoritative, up-to-date playbook for Fábrica. On "
        "FACTS about Fábrica (prices, shipping, policies, the subscription, the "
        "pre-launch embargo in §1) it OVERRIDES anything above. On HOW to behave "
        "(your identity, voice, formatting, language, safety) the configuration "
        "above still governs. Read §1 first and respect the embargo.\n"
        "=====================================================================\n\n"
        + _PLAYBOOK
    )
except FileNotFoundError:
    pass


def _serialize_content(content) -> list:
    """Convert Claude response content blocks to JSON-serializable dicts."""
    result = []
    for block in content:
        if hasattr(block, "text"):
            result.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            result.append({
                "type": "tool_use",
                "id": block.id,
                "name": block.name,
                "input": block.input,
            })
    return result


# Flag set by escalation tool during execution
_pending_escalation: dict[str, str] = {}


def flag_escalation(phone: str, summary: str):
    """Called by the escalation tool to flag this conversation for human mode."""
    _pending_escalation[phone] = summary


def _customer_llm_text(msg: dict) -> str:
    """Text to feed Claude for a stored customer message. Bea has no vision
    wiring, so a photo with no caption becomes a neutral placeholder instead
    of an empty turn — she still knows an attachment came in."""
    text = msg.get("text", "")
    if not text and msg.get("media"):
        text = "[O cliente enviou uma foto sem legenda / Customer sent a photo without a caption]"
    return text


async def chat(phone_number: str, user_message: str, media: dict | None = None,
               channel: str = "whatsapp") -> str:
    """Process a user message and return the agent's response.

    `media` is an optional {"mime_type", "data" (base64)} payload for a photo
    the customer attached — stored for the dashboard to display, but not
    passed to Claude (text/caption only; see _customer_llm_text).

    `channel` is "whatsapp" or "email"; it routes channel-specific tool actions
    (e.g. an invoice PDF is emailed for email conversations, sent on WhatsApp otherwise).
    """
    state = store.get_conversation(phone_number)
    customer_msg = {"role": "customer", "text": user_message, "ts": store.now_iso()}
    if media:
        customer_msg["media"] = media

    # Email is human-only. Human-mode WhatsApp stays silent until handback.
    if not should_agent_speak(
        "email" if (channel == "email" or state.get("channel") == "email") else "whatsapp",
        "human" if (channel == "email" or state.get("channel") == "email") else state.get("mode", "agent"),
    ):
        if channel == "email" or state.get("channel") == "email":
            state["channel"] = "email"
            state["mode"] = "human"
            if not state.get("escalation_summary"):
                state["escalation_summary"] = "Email — waiting for the team"
        state["messages"].append(customer_msg)
        store.save_conversation(phone_number, state)
        return None

    state["channel"] = channel

    # Build Claude messages from the most recent history (full history is kept
    # in storage for the dashboard; only the recent part is sent to the LLM).
    claude_messages = []
    for msg in state["messages"][-store.LLM_CONTEXT_MESSAGES:]:
        role = msg.get("role")
        if role == "customer":
            target, text = "user", _customer_llm_text(msg)
        elif role == "assistant":
            target = "assistant"
            text = "".join(
                b.get("text", "") for b in msg.get("content", [])
                if isinstance(b, dict) and b.get("type") == "text"
            )
        elif role == "human":
            # A team member's manually-sent message (e.g. the opener from
            # "Start a new conversation", or a reply sent during human
            # takeover) — Bea needs this in context too, so she doesn't
            # repeat questions or contradict what the team already told them.
            target, text = "assistant", msg.get("text", "")
        else:
            continue

        if claude_messages and claude_messages[-1]["role"] == target:
            # Anthropic requires strict user/assistant alternation — merge
            # consecutive same-role turns (e.g. two manual replies in a row
            # with no customer reply in between) instead of sending them as
            # separate turns, which the API would reject.
            claude_messages[-1]["content"] += "\n" + text
        else:
            claude_messages.append({"role": target, "content": text})

    live_text = _customer_llm_text(customer_msg)
    if claude_messages and claude_messages[-1]["role"] == "user":
        # Guards the same alternation requirement in the rare case history
        # ends on an unanswered customer turn (e.g. a prior run errored out
        # after recording the message but before replying).
        claude_messages[-1]["content"] += "\n" + live_text
    else:
        claude_messages.append({"role": "user", "content": live_text})

    # The Anthropic API requires the message list to START with a 'user' turn.
    # When the team opens a conversation (via "Start a new conversation"), the
    # only prior history is their message — mapped to an 'assistant' turn — so
    # the list would start with 'assistant' and the API would reject it,
    # leaving Bea unable to reply. Drop any leading assistant turns.
    while claude_messages and claude_messages[0]["role"] == "assistant":
        claude_messages.pop(0)

    # Record the customer message in history immediately so the stored order
    # stays chronological (customer first, then Bea's reply).
    state["messages"].append(customer_msg)

    # Give Bea today's date so she can reason about dates. The big static prompt
    # (incl. the ~10k-token playbook) is a cached block so it isn't re-billed on
    # every message; the tiny date block follows it, uncached.
    today = datetime.now(timezone.utc).strftime("%A, %d %B %Y")
    context_note = f"Today's date is {today}."
    dated_system = [
        {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": context_note},
    ]

    response = await client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=dated_system,
        tools=TOOL_DEFINITIONS,
        messages=claude_messages,
    )

    while response.stop_reason == "tool_use":
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result = await execute_tool(block.name, block.input, phone_number, channel=channel)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

        serialized = _serialize_content(response.content)
        claude_messages.append({"role": "assistant", "content": serialized})
        claude_messages.append({"role": "user", "content": tool_results})
        # NOTE: tool_use / tool_results are internal — kept only in
        # claude_messages for this turn, not persisted to display history.

        response = await client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=dated_system,
            tools=TOOL_DEFINITIONS,
            messages=claude_messages,
        )

    assistant_text = ""
    for block in response.content:
        if hasattr(block, "text"):
            assistant_text += block.text

    # Safety net: never bounce a WhatsApp customer to the support mailbox.
    if assistant_text:
        assistant_text, _ = scrub_support_mailbox_deflection(
            assistant_text, user_message
        )

    # Check if escalation was triggered during tool execution
    if phone_number in _pending_escalation:
        state["mode"] = "human"
        state["escalation_summary"] = _pending_escalation.pop(phone_number)
        # Log the escalation event (timestamped) so the dashboard can report
        # case volume over time, independent of the conversation's current state.
        state.setdefault("escalations", []).append({
            "ts": store.now_iso(),
            "summary": state["escalation_summary"],
        })

    # Save Bea's reply after the customer message (already recorded above)
    state["messages"].append({"role": "assistant", "content": [{"type": "text", "text": assistant_text}], "ts": store.now_iso()})
    store.save_conversation(phone_number, state)

    return assistant_text
