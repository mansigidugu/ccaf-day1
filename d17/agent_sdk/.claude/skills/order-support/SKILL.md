---
name: order-support
description: Rules for answering a customer's question about an order - its status, carrier, delivery ETA, who placed it, or what it was worth. Use this whenever the customer mentions an order or asks where their order is.
---

# Order support

Always look up the order with the tools before answering. Never guess a status,
a carrier, an ETA, a customer name, an email, or an order value.

Pick the tool that matches what was actually asked:

- `get_order_status` - status, carrier, days until arrival
- `get_customer_for_order` - who placed it: name and email
- `get_order_value` - what it was worth, and its category

If a question needs more than one of these, call each one you need.
Do not call a tool whose data was not asked for.

If a lookup returns an error, say so plainly and ask the customer to re-check
the order ID. Do not invent an order.

If a field comes back empty or unknown, say that plainly instead of filling in
a guess.

Keep replies to 2-3 sentences.