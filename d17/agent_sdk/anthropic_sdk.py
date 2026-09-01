"""
anthropic_sdk.py -- the SAME agent, written with the raw Anthropic SDK.

This exists purely for the side-by-side in the demo. Same three tools, same
sheet, same rules -- the only difference is WHO RUNS THE LOOP.

Read this file next to agent_sdk_teaching.py -- the contrast is the whole lesson:

    agent_sdk_teaching.py            anthropic_sdk.py  (this file)
    -------------------------------  ------------------------------------
    3 @tool functions                3 functions + a hand-written JSON schema
    register the list, once          build a `tools=[...]` array by hand
    `async for m in query(...)`      `for round_num in range(MAX_ROUNDS)`
    -- the SDK loops                 you check stop_reason yourself
    -- the SDK runs the tool         you dispatch on tool_call.name yourself
    -- the SDK feeds results back    you append tool_result to messages
    -- the SDK counts turns          you count rounds, and cap them

Everything marked "YOU DO THIS" below is machinery the Agent SDK deletes.
"""

import json
import os

from anthropic import Anthropic
from dotenv import load_dotenv

# Reuse the sheet reader and the model constant, so the only thing that
# differs between the two files is the loop itself.
from agent_sdk_teaching import MODEL, load_orders

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".env"))

# The safety cap. The Agent SDK calls this max_turns and enforces it for you;
# here it is a range() you must remember to write.
MAX_ROUNDS = 6

# In the Agent SDK this one line is `system_prompt=` and the real rules live
# in SKILL.md. With the raw SDK there is no Skill system, so every rule has
# to be crammed in here by hand.
SYSTEM = (
    "You are a concise order-support agent. "
    "Always look up the order with the tools before answering -- never guess a "
    "status, carrier, ETA, customer name, email, or order value. "
    "Pick the tool that matches what was asked, and call more than one if the "
    "question needs it. If a lookup returns an error, say so plainly and ask "
    "the customer to re-check the order ID. Keep replies to 2-3 sentences."
)


# ---------------------------------------------------------------- the tools
# YOU DO THIS: the same three functions, but the schema is hand-written JSON
# instead of coming from a decorator.
def get_order_status(order_id: str) -> dict:
    order = load_orders().get(order_id.strip())
    if order is None:
        return {"error": "order not found"}
    return {k: order[k] for k in ("status", "carrier", "eta_days")}


def get_customer_for_order(order_id: str) -> dict:
    order = load_orders().get(order_id.strip())
    if order is None:
        return {"error": "order not found"}
    return {k: order[k] for k in ("customer_name", "customer_email")}


def get_order_value(order_id: str) -> dict:
    order = load_orders().get(order_id.strip())
    if order is None:
        return {"error": "order not found"}
    return {k: order[k] for k in ("order_value", "category")}


# YOU DO THIS: the dispatch table. The Agent SDK never needs one -- it knows
# which function a tool name belongs to, because you registered them.
DISPATCH = {
    "get_order_status": get_order_status,
    "get_customer_for_order": get_customer_for_order,
    "get_order_value": get_order_value,
}

# YOU DO THIS: every schema, by hand. Compare with the @tool decorator, which
# generates all of this from {"order_id": str}.
TOOLS = [
    {
        "name": "get_order_status",
        "description": (
            "Get the shipping status of an order: its status, carrier, and how "
            "many days until it arrives."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "string", "description": "Order ID"}},
            "required": ["order_id"],
        },
    },
    {
        "name": "get_customer_for_order",
        "description": (
            "Get the customer who placed an order: their name and email address."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "string", "description": "Order ID"}},
            "required": ["order_id"],
        },
    },
    {
        "name": "get_order_value",
        "description": (
            "Get how much an order was worth and what product category it is in."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "string", "description": "Order ID"}},
            "required": ["order_id"],
        },
    },
]


# ------------------------------------------------------- THE LOOP YOU WRITE
def run_anthropic_loop(question: str):
    """The hand-written agent loop. Yields ("event", payload) as it goes, so
    the demo can show each round appearing.

    Every line in here is machinery the Agent SDK would have run for you.
    """
    client = Anthropic()
    messages = [{"role": "user", "content": question}]
    tool_calls = 0

    # YOU DO THIS: the loop, and the cap on it.
    for round_num in range(1, MAX_ROUNDS + 1):
        yield ("round", round_num)

        # YOU DO THIS: every call, with the full history resent each time.
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM,
            tools=TOOLS,
            messages=messages,
        )
        yield ("usage", response.usage)

        # YOU DO THIS: append the assistant turn to the history yourself.
        messages.append({"role": "assistant", "content": response.content})

        # YOU DO THIS: read stop_reason and decide what happens next.
        if response.stop_reason == "tool_use":
            # A turn can hold more than one tool call, so this is a loop too.
            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                tool_calls += 1
                yield ("tool_call", (block.name, block.input))

                # YOU DO THIS: dispatch on the tool name by hand.
                fn = DISPATCH[block.name]
                result = fn(**block.input)
                yield ("tool_result", (block.name, result))

                # YOU DO THIS: build the tool_result block the API expects.
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                    }
                )

            # YOU DO THIS: feed the results back as a new user turn.
            messages.append({"role": "user", "content": results})
            continue

        if response.stop_reason == "end_turn":
            text = next(
                (b.text for b in response.content if b.type == "text"), ""
            )
            yield ("answer", text)
            yield ("done", {"rounds": round_num, "tool_calls": tool_calls})
            return

        # YOU DO THIS: handle every other stop_reason yourself.
        yield ("stopped", response.stop_reason)
        yield ("done", {"rounds": round_num, "tool_calls": tool_calls})
        return

    # YOU DO THIS: notice you hit the cap, and say so.
    yield ("capped", MAX_ROUNDS)
    yield ("done", {"rounds": MAX_ROUNDS, "tool_calls": tool_calls})


if __name__ == "__main__":
    QUESTION = "Who placed order 1001, and how much was it worth?"
    print(f"Question: {QUESTION}\n")
    for kind, payload in run_anthropic_loop(QUESTION):
        if kind == "round":
            print(f"--- Round {payload} ---   (a round YOU wrote)")
        elif kind == "tool_call":
            print(f"    you dispatch: {payload[0]}({payload[1]})")
        elif kind == "tool_result":
            print(f"    you feed back: {payload[1]}")
        elif kind == "answer":
            print(f"\nClaude: {payload}")
        elif kind == "done":
            print(
                f"\nFinished in {payload['rounds']} round(s), "
                f"{payload['tool_calls']} tool call(s) -- all counted by you."
            )
