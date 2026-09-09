"""HUMANO brand knowledge for Fábrica Coffee Roasters' support agent.

HUMANO is Fábrica's retail/supermarket-facing specialty coffee brand, sold
in retailers/supermarkets and directly online. It runs on its own Shopify
store (separate credentials, see config.py / shopify_client.py) — Bea can
look up HUMANO orders and products the same way she does for Fábrica, by
passing brand="humano" to the relevant tools.

Edit this file to refine how Bea talks about HUMANO. Source: https://humano.coffee
"""

HUMANO_INFO_READY = True

HUMANO_INFO = """
**What HUMANO is**
- HUMANO® is Fábrica's sister specialty-coffee brand, made for retailers and
  supermarkets — an easy, approachable everyday specialty coffee. Tagline:
  "Specialty Coffee, as easy as it gets."
- Customers can also buy directly online at https://humano.coffee.
- HUMANO is a separate brand/store from Fábrica — if a customer's order or
  question is about HUMANO, use brand="humano" on the relevant tools
  (search_products, lookup_order, lookup_orders_by_email, get_customer_details,
  get_order_fulfillments). If unsure which brand an order belongs to, lookup_order
  will auto-check Fábrica then HUMANO when no brand is given.

**Products** (confirm current pricing/stock with search_products, brand="humano")
- Four coffee blends, 250g bags: Espresso, Latte, Filter, Decaf.
- Also stocks brewing equipment: grinders, AeroPress, Moka pots.

**Support scope**
- Bea can look up HUMANO orders and tracking the same way as for Fábrica.
- Invoices for HUMANO orders are not yet wired up — if a HUMANO customer asks
  for an invoice/fatura, do NOT use the send_invoice tool (it's Fábrica-only).
  Escalate to the human team instead via escalate_to_human.
"""


def humano_prompt_section() -> str:
    """Return the HUMANO brand section for Bea's system prompt."""
    if not HUMANO_INFO_READY:
        return ""
    return (
        "\n## HUMANO brand\n"
        "In addition to Fábrica, we also run HUMANO, a retail/supermarket "
        "specialty coffee brand. Use the knowledge below when a customer asks "
        "about HUMANO, mentions humano.coffee, or their order turns out to be "
        "a HUMANO order.\n" + HUMANO_INFO
    )
