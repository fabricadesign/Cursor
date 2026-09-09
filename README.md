# Fábrica Coffee Roasters — Customer Support Agent

Bilingual (PT/EN) WhatsApp customer support agent powered by Claude, integrated with Shopify and DPD Portugal.

## Quick Start

```bash
# 1. Create virtual environment
python -m venv .venv
.venv\Scripts\activate       # Windows
# source .venv/bin/activate  # Mac/Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure credentials
copy .env.example .env
# Edit .env with your API keys (see sections below)

# 4. Validate setup
python check_setup.py

# 5. Run
uvicorn main:app --host 0.0.0.0 --port 8000
```

## Credential Setup

### Anthropic (Claude)
1. Go to https://console.anthropic.com/settings/keys
2. Create an API key
3. Set `ANTHROPIC_API_KEY` in `.env`

### Shopify
1. Go to **Shopify Admin → Settings → Apps and sales channels → Develop apps**
2. Click **Create an app** → give it a name (e.g. "Support Agent")
3. **Configure Admin API scopes** — enable:
   - `read_orders`
   - `read_customers`
   - `read_fulfillments`
4. Click **Install app** → copy the **Admin API access token**
5. Set in `.env`:
   - `SHOPIFY_STORE_DOMAIN` = your store's `.myshopify.com` domain
   - `SHOPIFY_ACCESS_TOKEN` = the token you just copied

### DPD Portugal
DPD uses a SOAP API. You need a **delisId** and **password** from DPD Portugal.

1. Contact your DPD Portugal account manager to request API access
2. They will provide a delisId (username) and password
3. Confirm the API base URL (expected: `https://wsshipper.dpd.pt/soap`)
4. Set `DPD_USERNAME`, `DPD_PASSWORD`, and `DPD_API_URL` in `.env`

**Alternative — AfterShip (easier):** If the DPD SOAP API is difficult to set up, you can use AfterShip as a tracking aggregator:
1. Sign up at https://www.aftership.com
2. Get an API key
3. Set `AFTERSHIP_API_KEY` in `.env`
4. In `tools.py`, change the import to: `import dpd_client_aftership as dpd_client`

### WhatsApp Cloud API
1. Go to https://developers.facebook.com → **Create App** → choose **Business** type
2. Add the **WhatsApp** product to your app
3. In **WhatsApp → API Setup**:
   - Note your **Phone Number ID**
   - Generate a **Permanent Access Token** (via System User in Meta Business Settings)
4. In **WhatsApp → Configuration**:
   - Set **Webhook URL** to `https://your-domain.com/webhook`
   - Set **Verify Token** to a random string (must match `WHATSAPP_VERIFY_TOKEN` in `.env`)
   - Subscribe to the **messages** webhook field
5. Set all three `WHATSAPP_*` values in `.env`

**For local testing**, use [ngrok](https://ngrok.com) to get an HTTPS URL:
```bash
ngrok http 8000
# Use the https://xxxx.ngrok.io URL as your webhook URL in Meta
```

## Architecture

```
Customer (WhatsApp)
    ↓
POST /webhook (FastAPI)
    ↓
agent.py → Claude (sonnet-4-6)
    ↓ tool calls
shopify_client.py → Shopify Admin API (orders, customers, fulfillments)
dpd_client.py     → DPD SOAP API (parcel tracking)
    ↓
Claude composes response (PT or EN)
    ↓
whatsapp.py → WhatsApp Cloud API → Customer
```

## What the Agent Can Do

- Look up orders by number or customer email
- Show order status, items, prices, and shipping address
- Track DPD shipments and show delivery estimates
- Pull full customer profile from Shopify
- Automatically respond in Portuguese or English
- Escalate issues it cannot resolve

## Files

| File | Purpose |
|------|---------|
| `main.py` | FastAPI server with WhatsApp webhook |
| `agent.py` | Claude conversation loop with tool execution |
| `tools.py` | Tool definitions and execution handlers |
| `shopify_client.py` | Shopify Admin REST API client |
| `dpd_client.py` | DPD SOAP tracking client |
| `dpd_client_aftership.py` | Alternative: AfterShip REST tracking client |
| `whatsapp.py` | WhatsApp Cloud API message handling |
| `config.py` | Environment configuration |
| `check_setup.py` | Validates all API connections |

## Production Notes

- Use a reverse proxy (nginx/Caddy) with HTTPS — WhatsApp requires it
- Conversation history is stored in-memory — for production, use Redis or a database
- DPD auth tokens are cached but expire daily — the client handles re-authentication
- Shopify REST API is legacy; consider migrating to GraphQL for new features
- Rate limits: Shopify (2 req/s), DPD (10 logins/day, 30 shipments/min)
