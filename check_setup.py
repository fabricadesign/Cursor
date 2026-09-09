"""Validates that all API credentials are configured and working."""

import asyncio
import sys
import httpx


def check_env():
    """Check that .env file exists and all required vars are set."""
    print("1/5  Checking .env configuration...")
    try:
        from config import settings
    except Exception as e:
        print(f"  FAIL: Could not load .env — {e}")
        print("  → Copy .env.example to .env and fill in your credentials")
        sys.exit(1)

    missing = []
    if not settings.anthropic_api_key or settings.anthropic_api_key.startswith("sk-ant-..."):
        missing.append("ANTHROPIC_API_KEY")
    if not settings.shopify_store_domain or "your-store" in settings.shopify_store_domain:
        missing.append("SHOPIFY_STORE_DOMAIN")
    if not settings.shopify_client_id:
        missing.append("SHOPIFY_CLIENT_ID")
    if not settings.shopify_client_secret:
        missing.append("SHOPIFY_CLIENT_SECRET")
    optional_missing = []
    if not settings.whatsapp_phone_number_id or settings.whatsapp_phone_number_id == "123456789012345":
        optional_missing.append("WHATSAPP_PHONE_NUMBER_ID")
    if not settings.whatsapp_access_token or settings.whatsapp_access_token.startswith("EAAG..."):
        optional_missing.append("WHATSAPP_ACCESS_TOKEN")
    if not settings.humano_shopify_store_domain:
        optional_missing.append("HUMANO_SHOPIFY_STORE_DOMAIN")
    if not settings.humano_shopify_client_id:
        optional_missing.append("HUMANO_SHOPIFY_CLIENT_ID")
    if not settings.humano_shopify_client_secret:
        optional_missing.append("HUMANO_SHOPIFY_CLIENT_SECRET")

    if missing:
        print(f"  FAIL: Missing or placeholder values: {', '.join(missing)}")
        sys.exit(1)
    if optional_missing:
        print(f"  WARN: Not configured (optional): {', '.join(optional_missing)}")
    print("  OK")
    return settings


async def check_anthropic(settings):
    print("2/5  Testing Anthropic API key...")
    import anthropic
    try:
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        resp = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=10,
            messages=[{"role": "user", "content": "Say hi"}],
        )
        reply_text = resp.content[0].text.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(sys.stdout.encoding or "utf-8")
        print(f"  OK — Claude responded: {reply_text}")
    except Exception as e:
        print(f"  FAIL: {e}")


async def check_shopify(settings):
    print("3/5  Testing Shopify API access...")
    # Step 1: Get access token via client credentials
    async with httpx.AsyncClient() as client:
        try:
            token_resp = await client.post(
                f"https://{settings.shopify_store_domain}/admin/oauth/access_token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": settings.shopify_client_id,
                    "client_secret": settings.shopify_client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if token_resp.status_code != 200:
                print(f"  FAIL: Could not get access token — HTTP {token_resp.status_code}: {token_resp.text[:200]}")
                return
            token = token_resp.json()["access_token"]
            print(f"  Token obtained (expires in {token_resp.json().get('expires_in', '?')}s)")
        except Exception as e:
            print(f"  FAIL: Token request error — {e}")
            return

        # Step 2: Test the token
        try:
            url = f"https://{settings.shopify_store_domain}/admin/api/2024-10/orders/count.json?status=any"
            headers = {
                "X-Shopify-Access-Token": token,
                "Content-Type": "application/json",
            }
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                count = resp.json().get("count", "?")
                print(f"  OK — Found {count} orders in your store")
            elif resp.status_code == 401:
                print("  FAIL: Invalid access token")
            elif resp.status_code == 404:
                print(f"  FAIL: Store domain not found — check SHOPIFY_STORE_DOMAIN")
            else:
                print(f"  FAIL: HTTP {resp.status_code} — {resp.text[:200]}")
        except Exception as e:
            print(f"  FAIL: {e}")


async def check_humano_shopify(settings):
    print("4/5  Testing HUMANO Shopify API access...")
    if not (settings.humano_shopify_store_domain and settings.humano_shopify_client_id and settings.humano_shopify_client_secret):
        print("  SKIP: HUMANO_SHOPIFY_* not configured yet")
        return
    async with httpx.AsyncClient() as client:
        try:
            token_resp = await client.post(
                f"https://{settings.humano_shopify_store_domain}/admin/oauth/access_token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": settings.humano_shopify_client_id,
                    "client_secret": settings.humano_shopify_client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if token_resp.status_code != 200:
                print(f"  FAIL: Could not get access token — HTTP {token_resp.status_code}: {token_resp.text[:200]}")
                return
            token = token_resp.json()["access_token"]
            print(f"  Token obtained (expires in {token_resp.json().get('expires_in', '?')}s)")
        except Exception as e:
            print(f"  FAIL: Token request error — {e}")
            return

        try:
            url = f"https://{settings.humano_shopify_store_domain}/admin/api/2024-10/orders/count.json?status=any"
            headers = {
                "X-Shopify-Access-Token": token,
                "Content-Type": "application/json",
            }
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                count = resp.json().get("count", "?")
                print(f"  OK — Found {count} orders in the HUMANO store")
            elif resp.status_code == 401:
                print("  FAIL: Invalid access token")
            elif resp.status_code == 404:
                print(f"  FAIL: Store domain not found — check HUMANO_SHOPIFY_STORE_DOMAIN")
            else:
                print(f"  FAIL: HTTP {resp.status_code} — {resp.text[:200]}")
        except Exception as e:
            print(f"  FAIL: {e}")


async def check_whatsapp(settings):
    print("5/5  Testing WhatsApp Cloud API...")
    url = f"https://graph.facebook.com/v21.0/{settings.whatsapp_phone_number_id}"
    headers = {"Authorization": f"Bearer {settings.whatsapp_access_token}"}
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                print(f"  OK — Phone: {data.get('display_phone_number', 'connected')}")
            elif resp.status_code == 190:
                print("  FAIL: Access token expired — generate a new one in Meta Business")
            else:
                print(f"  WARN: HTTP {resp.status_code} — {resp.text[:200]}")
        except Exception as e:
            print(f"  FAIL: {e}")


async def main():
    print("=" * 50)
    print("Fábrica Support Agent — Setup Check")
    print("=" * 50)
    s = check_env()
    await check_anthropic(s)
    await check_shopify(s)
    await check_humano_shopify(s)
    await check_whatsapp(s)
    print("=" * 50)
    print("Done! If all checks passed, run: uvicorn main:app --port 8000")


if __name__ == "__main__":
    asyncio.run(main())
