"""Tool definitions for the Claude agent and their execution handlers."""

import json
import shopify_client
import dpd_client
import invoicexpress_client
import recharge_client
import email_client
import whatsapp
import notifications

TOOL_DEFINITIONS = [
    {
        "name": "lookup_order",
        "description": "Look up a Shopify order by its order number (e.g. '#1042' or '1042'). Returns order details including status, items, shipping address, and fulfillment info. Works for both Fábrica and HUMANO orders.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_number": {
                    "type": "string",
                    "description": "The order number, with or without '#' prefix",
                },
                "brand": {
                    "type": "string",
                    "enum": ["fabrica", "humano"],
                    "description": "Which brand's store the order belongs to. Pass 'humano' if the customer mentions HUMANO or humano.coffee. Leave empty to auto-detect (checks Fábrica first, then HUMANO).",
                },
            },
            "required": ["order_number"],
        },
    },
    {
        "name": "lookup_orders_by_email",
        "description": "Find all recent orders for a customer by their email address. Returns up to 5 most recent orders. Searches both Fábrica and HUMANO unless a brand is specified.",
        "input_schema": {
            "type": "object",
            "properties": {
                "email": {
                    "type": "string",
                    "description": "Customer email address",
                },
                "brand": {
                    "type": "string",
                    "enum": ["fabrica", "humano"],
                    "description": "Restrict the search to one brand's store. Leave empty to search both.",
                },
            },
            "required": ["email"],
        },
    },
    {
        "name": "get_customer_details",
        "description": "Get full customer profile from Shopify including name, email, phone, addresses, and order count.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "integer",
                    "description": "Shopify customer ID",
                },
                "brand": {
                    "type": "string",
                    "enum": ["fabrica", "humano"],
                    "description": "Which brand's store this customer ID belongs to — use the same brand as the order it came from. Defaults to 'fabrica'.",
                },
            },
            "required": ["customer_id"],
        },
    },
    {
        "name": "find_customer",
        "description": "Search for a customer directly in Shopify by email, phone, or name — use this when a customer asks about their account/profile/order history and you do NOT already have an order number or an email tied to a specific order. Returns matching customer profiles (name, email, phone, order count, addresses). Try this before telling a customer you can't find their information.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Email, phone number, or name to search for",
                },
                "brand": {
                    "type": "string",
                    "enum": ["fabrica", "humano"],
                    "description": "Which brand's customer list to search. Defaults to 'fabrica'.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "track_shipment",
        "description": "Track a DPD shipment by its tracking number. Returns current status, latest event, and estimated delivery date.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tracking_number": {
                    "type": "string",
                    "description": "DPD tracking/parcel number",
                }
            },
            "required": ["tracking_number"],
        },
    },
    {
        "name": "get_order_fulfillments",
        "description": "Get all fulfillment/shipping details for an order, including tracking numbers and shipment status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "integer",
                    "description": "Shopify order ID (internal ID, not display number)",
                },
                "brand": {
                    "type": "string",
                    "enum": ["fabrica", "humano"],
                    "description": "Which brand's store this order ID belongs to — use the same brand as the order it came from. Defaults to 'fabrica'.",
                },
            },
            "required": ["order_id"],
        },
    },
    {
        "name": "search_products",
        "description": "Search a brand's live product catalogue (e.g. 'espresso', 'decaf', 'chemex', a coffee name, or a product category). Returns matching active products with their variants, prices, and current stock levels. Use this whenever a customer asks whether something is available, in stock, or for details on specific products — do not guess. Defaults to the Fábrica catalogue; pass brand='humano' for HUMANO products.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword to search for, matched against product title, type and tags (e.g. 'espresso', 'v60', 'sample bag'). Leave empty to list all active products.",
                },
                "brand": {
                    "type": "string",
                    "enum": ["fabrica", "humano"],
                    "description": "Which brand's catalogue to search. Defaults to 'fabrica'.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "send_invoice",
        "description": "Handle a customer's invoice/'fatura'/'recibo' request. The customer MUST provide the order number, the email used on the order, AND their NIF (tax number). If the order's invoice already has a NIF, it is sent to the customer on WhatsApp. If it has no NIF yet, the request is forwarded to the team to reissue the invoice with the NIF.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_number": {
                    "type": "string",
                    "description": "The order number, with or without '#' prefix",
                },
                "email": {
                    "type": "string",
                    "description": "The email address the customer claims was used on the order (for identity verification)",
                },
                "nif": {
                    "type": "string",
                    "description": "The customer's NIF / tax number to appear on the invoice",
                },
            },
            "required": ["order_number", "email", "nif"],
        },
    },
    {
        "name": "lookup_subscription",
        "description": "Look up a customer's coffee subscription (Recharge) by the email on their account. Returns each active subscription's product, quantity, status, billing frequency, and next charge date. Use this when a subscriber asks about their subscription — status, when they'll be charged, when they'll get their next delivery, or what's in it. This is READ-ONLY: for any change (pause, skip, swap, cancel), do not attempt it — escalate to the team instead.",
        "input_schema": {
            "type": "object",
            "properties": {
                "email": {
                    "type": "string",
                    "description": "The email address on the customer's subscription account",
                },
            },
            "required": ["email"],
        },
    },
    {
        "name": "escalate_to_human",
        "description": "Escalate a customer issue to the human support team. Use this when: the customer requests a refund/cancellation, has an unresolvable complaint, asks to speak with a human, or there's a problem requiring manual intervention. An alert will be sent to the team via email and WhatsApp.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Clear summary of the customer's issue and what has been tried so far",
                },
                "customer_name": {
                    "type": "string",
                    "description": "Customer's name if known",
                },
                "order_number": {
                    "type": "string",
                    "description": "Related order number if applicable",
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "description": "Priority level: low (general inquiry), medium (order issue), high (complaint, urgent)",
                },
            },
            "required": ["summary"],
        },
    },
]


def _summarize_order(order: dict, brand: str = "fabrica") -> dict:
    """Extract the most relevant fields from a Shopify order."""
    line_items = [
        {"name": li["name"], "quantity": li["quantity"], "price": li["price"]}
        for li in order.get("line_items", [])
    ]
    shipping = order.get("shipping_address") or {}
    fulfillments = order.get("fulfillments", [])
    tracking_numbers = []
    for f in fulfillments:
        tracking_numbers.extend(f.get("tracking_numbers", []))

    return {
        "brand": brand,
        "order_id": order["id"],
        "order_number": order.get("name", order.get("order_number")),
        "email": order.get("email"),
        "financial_status": order.get("financial_status"),
        "fulfillment_status": order.get("fulfillment_status") or "unfulfilled",
        "created_at": order.get("created_at"),
        "total_price": order.get("total_price"),
        "currency": order.get("currency"),
        "items": line_items,
        "shipping_name": f"{shipping.get('first_name', '')} {shipping.get('last_name', '')}".strip(),
        "shipping_address": ", ".join(
            filter(None, [
                shipping.get("address1"),
                shipping.get("address2"),
                shipping.get("city"),
                shipping.get("zip"),
                shipping.get("country"),
            ])
        ),
        "shipping_phone": shipping.get("phone"),
        "tracking_numbers": tracking_numbers,
        "customer_id": order.get("customer", {}).get("id"),
    }


def _summarize_product(product: dict, brand: str = "fabrica") -> dict:
    """Extract the fields Bea needs to talk about a product and its stock."""
    variants = []
    for v in product.get("variants", []):
        qty = v.get("inventory_quantity")
        oversell = v.get("inventory_policy") == "continue"
        in_stock = oversell or (qty is not None and qty > 0)
        variants.append({
            "title": v.get("title"),
            "price": v.get("price"),
            "in_stock": in_stock,
            "quantity": qty,
        })
    site_url = shopify_client.SITE_URLS.get(brand, shopify_client.SITE_URLS["fabrica"])
    return {
        "brand": brand,
        "title": product.get("title"),
        "category": product.get("product_type"),
        "tags": product.get("tags"),
        "url": f"{site_url}/products/{product.get('handle')}",
        "variants": variants,
    }


def _summarize_customer(customer: dict) -> dict:
    return {
        "id": customer["id"],
        "name": f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip(),
        "email": customer.get("email"),
        "phone": customer.get("phone"),
        "orders_count": customer.get("orders_count"),
        "total_spent": customer.get("total_spent"),
        "default_address": customer.get("default_address"),
        "created_at": customer.get("created_at"),
        "tags": customer.get("tags"),
    }


async def execute_tool(tool_name: str, tool_input: dict, customer_phone: str = "", channel: str = "whatsapp") -> str:
    """Execute a tool call and return the result as a JSON string."""
    try:
        if tool_name == "lookup_order":
            order_number = tool_input["order_number"]
            brand = tool_input.get("brand")
            if brand:
                store = shopify_client.get_store(brand)
                if not store.configured:
                    return json.dumps({"error": f"{store.name} order lookup is not connected yet."})
                order = await store.search_order(order_number)
                if not order:
                    return json.dumps({"error": "Order not found"})
                return json.dumps(_summarize_order(order, brand))

            # No brand given: try Fábrica first, then HUMANO if not found there.
            order = await shopify_client.fabrica.search_order(order_number)
            if order:
                return json.dumps(_summarize_order(order, "fabrica"))
            if shopify_client.humano.configured:
                order = await shopify_client.humano.search_order(order_number)
                if order:
                    return json.dumps(_summarize_order(order, "humano"))
            return json.dumps({"error": "Order not found"})

        elif tool_name == "lookup_orders_by_email":
            email = tool_input["email"]
            brand = tool_input.get("brand")
            if brand:
                store = shopify_client.get_store(brand)
                if not store.configured:
                    return json.dumps({"error": f"{store.name} order lookup is not connected yet."})
                orders = await store.search_orders_by_email(email)
                if not orders:
                    return json.dumps({"error": "No orders found for this email"})
                return json.dumps([_summarize_order(o, brand) for o in orders])

            # No brand given: search both stores and merge results.
            results = [_summarize_order(o, "fabrica") for o in await shopify_client.fabrica.search_orders_by_email(email)]
            if shopify_client.humano.configured:
                results += [_summarize_order(o, "humano") for o in await shopify_client.humano.search_orders_by_email(email)]
            if not results:
                return json.dumps({"error": "No orders found for this email"})
            return json.dumps(results)

        elif tool_name == "find_customer":
            brand = tool_input.get("brand", "fabrica")
            store = shopify_client.get_store(brand)
            if not store.configured:
                return json.dumps({"error": f"{store.name} customer lookup is not connected yet."})
            customers = await store.search_customers(tool_input["query"])
            if not customers:
                return json.dumps({"error": "No matching customer found."})
            return json.dumps([_summarize_customer(c) for c in customers])

        elif tool_name == "get_customer_details":
            store = shopify_client.get_store(tool_input.get("brand", "fabrica"))
            customer = await store.get_customer(tool_input["customer_id"])
            return json.dumps(_summarize_customer(customer))

        elif tool_name == "track_shipment":
            data = await dpd_client.track_parcel(tool_input["tracking_number"])
            if not data:
                return json.dumps({"error": "Tracking number not found"})
            return json.dumps(dpd_client.format_tracking_info(data))

        elif tool_name == "get_order_fulfillments":
            store = shopify_client.get_store(tool_input.get("brand", "fabrica"))
            fulfillments = await store.get_fulfillments(tool_input["order_id"])
            return json.dumps(fulfillments)

        elif tool_name == "search_products":
            brand = tool_input.get("brand", "fabrica")
            store = shopify_client.get_store(brand)
            if not store.configured:
                return json.dumps({"error": f"{store.name} product catalogue is not connected yet."})
            products = await store.search_products(tool_input.get("query", ""))
            if not products:
                return json.dumps({"error": "No matching products found in the catalogue."})
            return json.dumps([_summarize_product(p, brand) for p in products])

        elif tool_name == "lookup_subscription":
            if not recharge_client.configured():
                return json.dumps({"error": "Subscriptions are not connected yet."})
            email = (tool_input.get("email") or "").strip()
            customer = await recharge_client.find_customer_by_email(email)
            if not customer:
                return json.dumps({"error": "No subscription account found for that email. Ask the customer to confirm the email used for their subscription."})
            subs = await recharge_client.get_subscriptions(customer["id"])
            if not subs:
                return json.dumps({"subscriptions": [], "message": "This customer has no subscriptions on file."})
            return json.dumps({
                "subscriptions": [recharge_client.summarize_subscription(s) for s in subs],
                "note": "READ-ONLY. For any change (pause/skip/swap/cancel), escalate to the team.",
            })

        elif tool_name == "send_invoice":
            order_number = tool_input["order_number"]
            claimed_email = (tool_input.get("email") or "").strip().lower()
            nif = (tool_input.get("nif") or "").strip()

            invoice = await invoicexpress_client.find_invoice_by_order(order_number)
            if not invoice:
                return json.dumps({"error": "No invoice found for that order number."})

            # Identity check: the email on the invoice must match what the customer provided
            invoice_email = (invoice.get("client", {}).get("email") or "").strip().lower()
            if not claimed_email or claimed_email != invoice_email:
                return json.dumps({
                    "error": "email_mismatch",
                    "message": "The email provided does not match the order. Ask the customer to confirm the email used on the order. Do NOT reveal the correct email.",
                })

            # Does the order's invoice already carry a NIF?
            client_id = invoice.get("client", {}).get("id")
            existing_nif = await invoicexpress_client.get_client_fiscal_id(client_id) if client_id else ""

            if existing_nif:
                # Already has a NIF — just send the existing invoice PDF
                pdf_url = await invoicexpress_client.get_invoice_pdf_url(invoice["id"])
                if not pdf_url:
                    return json.dumps({"error": "Could not generate the invoice PDF. Ask the customer to try again shortly."})
                seq = invoice.get("sequence_number", "invoice").replace("/", "-")
                filename = f"Fatura-{seq}.pdf"
                caption = f"A sua fatura da encomenda {order_number} / Your invoice for order {order_number}"
                if customer_phone and channel == "email":
                    # Email the PDF as an attachment to the customer's address
                    import httpx as _httpx
                    async with _httpx.AsyncClient(timeout=30) as _c:
                        pdf_bytes = (await _c.get(pdf_url)).content
                    email_client.send_email_reply(
                        customer_phone, "A sua fatura / Your invoice",
                        caption, attachments=[(filename, pdf_bytes, "application/pdf")],
                    )
                elif customer_phone:
                    await whatsapp.send_document(customer_phone, pdf_url, filename, caption=caption)
                return json.dumps({
                    "status": "sent",
                    "invoice_number": invoice.get("sequence_number"),
                    "message": "The invoice already includes a NIF and was sent to the customer. Confirm warmly that it has been sent.",
                })

            # No NIF on the order's invoice — forward to the team to reissue with the NIF
            summary = (
                f"Invoice reissue requested WITH NIF.\n"
                f"Order: {order_number}\nEmail: {claimed_email}\nNIF to add: {nif}\n"
                f"Original invoice: {invoice.get('sequence_number')} (currently without NIF)."
            )
            from agent import flag_escalation
            flag_escalation(customer_phone, summary)
            await notifications.send_escalation_alert(
                customer_phone=customer_phone,
                summary=summary,
                customer_name=invoice.get("client", {}).get("name", "Unknown"),
                order_number=order_number,
            )
            return json.dumps({
                "status": "forwarded_to_team",
                "message": "The order's invoice has no NIF yet, so it must be reissued by the team. Tell the customer warmly that their invoice will be reissued with their NIF and sent to them shortly by our team.",
            })

        elif tool_name == "escalate_to_human":
            summary = tool_input["summary"]
            from agent import flag_escalation
            flag_escalation(customer_phone, summary)
            result = await notifications.send_escalation_alert(
                customer_phone=customer_phone,
                summary=summary,
                customer_name=tool_input.get("customer_name", "Unknown"),
                order_number=tool_input.get("order_number", ""),
            )
            return json.dumps(result)

        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

    except Exception as e:
        return json.dumps({"error": str(e)})
