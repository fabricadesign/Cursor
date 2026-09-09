# Fábrica Coffee Roasters — Support Agent (Bea)

Source for the live WhatsApp agent: [github.com/fabricadesign/Cursor](https://github.com/fabricadesign/Cursor).

Bea answers **WhatsApp only**. Email to `support@fabricacoffeeroasters.com` is stored for the team — Bea does not reply there. When a teammate sends a WhatsApp reply, Bea stays silent until **Hand back to Agent**.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in keys
uvicorn main:app --host 127.0.0.1 --port 43124
```

Admin: `http://127.0.0.1:43124/admin`

```bash
python -m unittest tests.test_guardrails
```

## Credentials

`ANTHROPIC_API_KEY` is the secret (`sk-ant-…`). That is the only Anthropic password.

`ANTHROPIC_MODEL` is **not a key**. It is the model name from the [Anthropic console](https://console.anthropic.com) (for example `claude-sonnet-4-6` or `claude-opus-4-6`). Leave it blank to use the default.

Desk WhatsApp ping on escalate goes to `ALERT_WHATSAPP_NUMBER` (default `+351 912 338 809`). Meta rejects free-form messages after 24 hours (error 131047). Set `WHATSAPP_ESCALATION_TEMPLATE` to an approved template name so the ping still lands.

## What changed in this pass

- Email poll stores mail for humans; Bea never auto-replies on email.
- WhatsApp replies that tell the customer to email `support@…` are stripped.
- Human takeover already muted Bea; error apologies no longer talk over a human thread.
- Desk escalation ping defaults to the desk number and prefers a WhatsApp template.
