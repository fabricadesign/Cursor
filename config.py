from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Anthropic — the key is the sk-ant-… secret. ANTHROPIC_MODEL is the
    # product name from the Anthropic console (e.g. claude-sonnet-4-6), not
    # another key.
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"

    # Shopify (Dev Dashboard — Client Credentials flow)
    shopify_store_domain: str = ""
    shopify_client_id: str = ""
    shopify_client_secret: str = ""

    # HUMANO — separate Shopify store (retail/supermarket brand, humano.coffee)
    humano_shopify_store_domain: str = ""
    humano_shopify_client_id: str = ""
    humano_shopify_client_secret: str = ""

    # DPD (no credentials needed — uses public tracking)
    dpd_api_url: str = "https://wsshipper.dpd.pt/soap"
    dpd_username: str = ""
    dpd_password: str = ""

    # AfterShip API (alternative tracking)
    aftership_api_key: str = ""

    # InvoiceXpress (invoicing)
    invoicexpress_account: str = ""
    invoicexpress_api_key: str = ""

    # Recharge (subscriptions) — read-only API token
    recharge_api_token: str = ""

    # Support mailbox (support@fabricacoffeeroasters.com) — IMAP read + SMTP reply.
    # cPanel: host mail.fabricacoffeeroasters.com, IMAP 993 (SSL), SMTP 587 (STARTTLS).
    support_email_address: str = "support@fabricacoffeeroasters.com"
    support_email_password: str = ""
    support_imap_host: str = "mail.fabricacoffeeroasters.com"
    support_imap_port: int = 993
    support_smtp_host: str = "mail.fabricacoffeeroasters.com"
    support_smtp_port: int = 587
    # Secret guarding the email-poll endpoint (external scheduler calls it).
    email_poll_secret: str = "fabrica_poll_2026"

    # WhatsApp Cloud API
    whatsapp_phone_number_id: str = ""
    whatsapp_access_token: str = ""
    whatsapp_verify_token: str = ""

    # Approved WhatsApp message template for starting a conversation with a
    # customer who hasn't messaged us in the last 24h (required by WhatsApp —
    # free-form messages are rejected outside that window). Leave blank until
    # a template has been created and approved in Meta Business Manager.
    whatsapp_new_conversation_template: str = ""
    whatsapp_template_language: str = "pt_PT"

    # Escalation alerts. Desk handset that should receive the WhatsApp ping
    # when a conversation turns red ("needs human"). Empty used to silently
    # skip the ping. Default is the Fábrica desk number.
    alert_email_to: str = "info@fabricacoffeeroasters.com"
    alert_whatsapp_number: str = "+351912338809"
    # Approved Meta template for that desk ping. Session (free-form) texts
    # fail with Graph 131047 once 24h have passed since the desk last replied
    # to the business number. Leave blank to try the new-conversation template
    # next, then a session text as last resort.
    whatsapp_escalation_template: str = ""

    # Upstash Redis (for conversation history & human takeover)
    # Vercel auto-sets KV_REST_API_URL and KV_REST_API_TOKEN
    kv_rest_api_url: str = ""
    kv_rest_api_token: str = ""

    # Admin dashboard
    admin_password: str = "fabrica_admin_2026"

    # SMTP for email alerts
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("alert_whatsapp_number", mode="before")
    @classmethod
    def default_desk_number(cls, value: str | None) -> str:
        # Vercel often stores ALERT_WHATSAPP_NUMBER as an empty string, which
        # would otherwise override the default and skip the desk ping entirely.
        if isinstance(value, str) and value.strip():
            return value.strip()
        return "+351912338809"


settings = Settings()
