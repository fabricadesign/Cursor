"""Subscription policy knowledge for Fábrica Coffee Roasters.

Edit this file when the subscription policy changes.
Source: https://fabricacoffeeroasters.com/pages/faqs
"""

SUBSCRIPTION_INFO_READY = True

SUBSCRIPTION_INFO = """
**How the coffee subscription works**
- When a customer is charged in a given month, their coffee is roasted on the FIRST WEDNESDAY of the FOLLOWING month.
- It leaves our warehouse the NEXT DAY after roasting (i.e. the first Thursday of that month), via DPD.
  - Example: a subscriber charged on 1 July has their coffee roasted on the first Wednesday of August, and it leaves the warehouse the next day (Thursday).
- Actual delivery to the customer's address then depends on DPD transit time on top of that dispatch date.

**What's included**
- Up to 6 espresso and 6 filter coffee bags per month, with a choice of grind type for each.
- Espresso subscriptions include up to 2 different espresso coffees per shipment; mixed (filter + espresso) up to 4 varieties.

**Availability**
- The subscription ships to European Union countries only (European islands are not included).

**Payment options**
- Monthly, or pay upfront for quarterly, semi-annual or annual commitments at discounted rates.

**Managing a subscription**
- Payment method and delivery address can be changed in the customer dashboard under "Subscription".
- For other changes, pauses or cancellations, customers should email orders@fabricacoffeeroasters.com (self-service changes are not available yet).

**Delivery issues**
- Failed deliveries are automatically forwarded to a partner parcel shop, and the customer receives a notification email.
"""


def subscription_prompt_section() -> str:
    """Return the subscription-policy section for Bea's system prompt."""
    if not SUBSCRIPTION_INFO_READY:
        return ""
    return (
        "\n## Coffee subscription policy\n"
        "When customers ask about their subscription — billing, when they'll "
        "receive their coffee, what's included, or how to change/cancel — use "
        "the policy below. To work out the roast and dispatch dates: find the "
        "first Wednesday of the month AFTER the customer was charged (roast "
        "date); dispatch from the warehouse is the next day (that Thursday). "
        "Use today's date (given above) for any relative date reasoning. Work "
        "out the dates silently and state them directly and confidently — do "
        "NOT show your calculations or corrections. Be clear that the roast/"
        "dispatch date is not the same as the delivery date — actual arrival "
        "depends on DPD transit time after dispatch, so if the customer wants "
        "a precise delivery estimate, offer to track their shipment once it "
        "has a tracking number. For more detail beyond what's below, point "
        "the customer to https://fabricacoffeeroasters.com/pages/faqs or "
        "orders@fabricacoffeeroasters.com instead of guessing.\n"
        + SUBSCRIPTION_INFO
    )
