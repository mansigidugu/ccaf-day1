"""
agent_sdk_teaching.py -- the whole agent, in one file.

This file is the thing being demonstrated. agent_sdk_streamlit.py only reads it
and displays it. Everything the agent IS lives between the two AGENT DEFINITION
banner comments further down. The Streamlit app locates those banners and prints
their real line numbers on screen, so when you say "here is where the agent is
defined", the audience sees the exact lines.

WHAT THE AGENT DOES
    It answers customer questions about orders, using live data from a Google
    Sheet. It has THREE tools, and it picks which ones to call by itself:

        get_order_status(order_id)        status, carrier, days until arrival
        get_customer_for_order(order_id)  who placed it -- name and email
        get_order_value(order_id)         what it was worth, and its category

    Ask "who ordered 1001 and what was it worth?" and the agent works out that
    it needs two different tools, calls both, and combines the answers.

The one thing to point at: there is no loop in this file -- no round counter, no
stop-reason check, no dispatch on a tool name. The SDK runs all of that. Tab 3
of the demo greps this file to prove those four things are genuinely absent.
"""

import json
import os
import ssl
import urllib.request

import certifi
from dotenv import load_dotenv

# THE RENAME TRAP (deck slide 11): the package is claude_agent_sdk.
# The old claude_code_sdk / ClaudeCodeOptions names are deprecated and will
# not import. If you see those in a tutorial, the tutorial is stale.
from claude_agent_sdk import (
    ClaudeAgentOptions,
    create_sdk_mcp_server,
    query,
    tool,
)

# .env lives two folders up (week4 root), so one key file serves every day.
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".env"))

HERE = os.path.dirname(os.path.abspath(__file__))

# Pinned. fallback_model is the SAME string, so a busy model cannot silently
# promote us onto a bigger, pricier one.
MODEL = "claude-haiku-4-5-20251001"

# The SDK's spend cap: how many rounds its loop may run for one question.
# Loading the Skill and calling the tools each cost a turn, so this is not 2.
MAX_TURNS = 12

SYSTEM_PROMPT = "You are a concise order-support agent."


# ---------------------------------------------------------------- the data
# Verify Google's certificate against certifi's CA bundle instead of the
# machine's certificate store. Some Windows and corporate Python installs have
# an empty store, and then every HTTPS call dies with:
#     [SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer certificate
# certifi ships inside the venv, so this behaves the same on every machine.
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


# One read of the sheet serves all three tools. The Order tab has nine columns:
#   0 Order ID | 1 Status | 2 Carrier | 3 ETA Days | 4 Category
#   5 Delivery Date | 6 Customer Email | 7 Customer Name | 8 Order Value
def load_orders() -> dict:
    """Read the Order tab once -> {order_id: {column: value}}."""
    url = (
        "https://sheets.googleapis.com/v4/spreadsheets/"
        f"{os.getenv('GOOGLE_SHEET_ID')}/values:batchGet"
        f"?ranges=Order!A:Z&key={os.getenv('GOOGLE_API_KEY')}"
    )
    with urllib.request.urlopen(url, timeout=20, context=SSL_CONTEXT) as response:
        rows = json.load(response)["valueRanges"][0]["values"]

    orders = {}
    for row in rows[1:]:  # row 0 is the header
        # The Sheets API drops trailing blank cells, so a short row arrives with
        # fewer than 9 items. Pad to 9, or row[8] raises IndexError.
        row = (row + [""] * 9)[:9]
        if not row[0].strip():
            continue  # the sheet has blank spacer rows further down; skip them
        orders[row[0].strip()] = {
            "status": row[1],
            "carrier": row[2],
            "eta_days": int(row[3]) if row[3].isdigit() else row[3],
            "category": row[4],
            "delivery_date": row[5],
            "customer_email": row[6],
            "customer_name": row[7],
            "order_value": int(row[8]) if row[8].isdigit() else row[8],
        }
    return orders


def _lookup(order_id: str, *fields: str) -> dict:
    """Shared by all three tools: find the order, return only `fields`."""
    order = load_orders().get(order_id.strip())
    if order is None:
        return {"error": "order not found"}
    return {f: order[f] for f in fields}


def _as_tool_result(payload: dict) -> dict:
    """The shape every tool must return: content blocks the agent can read."""
    return {"content": [{"type": "text", "text": json.dumps(payload)}]}


#  ======================================================================
#  === AGENT DEFINITION : START =========================================
#  Everything from here to the END banner is the agent. Three pieces:
#     1. the tools     -- Python functions the agent may call
#     2. registering   -- how those functions are handed to the SDK
#     3. the options   -- every knob, in one object
#  ======================================================================

# --- 1. THE TOOLS ------------------------------------------------------
# Three tools, one job each. @tool takes (name, description, input schema).
#
# The DESCRIPTION is the important part: it is not a comment, it is the text
# the agent reads to decide WHICH tool to call. Three clearly-different
# descriptions are what let the agent route a question to the right one.


@tool(
    "get_order_status",
    "Get the shipping status of an order: its status, carrier, and how many "
    "days until it arrives. Use for 'where is my order' questions.",
    {"order_id": str},
)
async def get_order_status(args: dict) -> dict:
    # Note what is NOT here: no checking of a tool name, no dispatch table,
    # no feeding the result back. Just the lookup. The SDK does the rest.
    return _as_tool_result(
        _lookup(args["order_id"], "status", "carrier", "eta_days")
    )


@tool(
    "get_customer_for_order",
    "Get the customer who placed an order: their name and email address. "
    "Use for 'who ordered this' or 'what is their email' questions.",
    {"order_id": str},
)
async def get_customer_for_order(args: dict) -> dict:
    return _as_tool_result(
        _lookup(args["order_id"], "customer_name", "customer_email")
    )


@tool(
    "get_order_value",
    "Get how much an order was worth and what product category it is in. "
    "Use for 'how much did it cost' or 'what kind of product' questions.",
    {"order_id": str},
)
async def get_order_value(args: dict) -> dict:
    return _as_tool_result(
        _lookup(args["order_id"], "order_value", "category")
    )


# All three, in one list. This is what the agent is allowed to choose from.
ORDER_TOOLS = [get_order_status, get_customer_for_order, get_order_value]


# --- 2. REGISTERING THEM -----------------------------------------------
# Handing our functions to the SDK. They run in-process -- nothing is
# deployed, no port is opened, no separate process starts.
#
# The name "orders" below becomes each tool's prefix, which is why the
# allow-list further down says mcp__orders__get_order_status.
tool_registry = create_sdk_mcp_server(
    name="orders",
    version="1.0.0",
    tools=ORDER_TOOLS,
)

# The allow-list needs the full prefixed name of every tool.
TOOL_NAMES = [f"mcp__orders__{t.name}" for t in ORDER_TOOLS]


# --- 3. THE OPTIONS ----------------------------------------------------
# One object configures the whole agent. This is the agent's control panel.
def build_options(permission_mode: str = "dontAsk") -> ClaudeAgentOptions:
    """The agent's control panel. permission_mode is a parameter here only so
    the demo can flip it live and show the effect -- normally it is hard-coded."""
    return ClaudeAgentOptions(
        # Pin both, so nothing quietly runs on a bigger model.
        model=MODEL,
        fallback_model=MODEL,
        # Deliberately one line. The real rules live in the Skill, so they can
        # be edited without touching Python.
        system_prompt=SYSTEM_PROMPT,
        # Where our three tools come from.
        mcp_servers={"orders": tool_registry},
        # cwd finds .claude/skills/; setting_sources permits reading it.
        # Drop either one and the Skill silently never loads.
        cwd=HERE,
        setting_sources=["project"],
        skills=["order-support"],
        # THE ALLOW-LIST: our three tools, and nothing else. Read, Write, Bash
        # and WebSearch are ON by default -- an order agent needs none of them,
        # so they are simply not listed here.
        allowed_tools=TOOL_NAMES,
        # HARD BLOCKS. These win over everything, including bypassPermissions.
        # Belt and braces next to the allow-list above.
        disallowed_tools=["Bash", "Write", "Edit", "WebSearch", "WebFetch"],
        # Fail-closed: anything not allowed is denied, never prompted.
        # An unattended agent must never sit waiting on a prompt nobody sees.
        permission_mode=permission_mode,
        # The spend cap.
        max_turns=MAX_TURNS,
    )


#  === AGENT DEFINITION : END ===========================================
#  ======================================================================


# ---------------------------------------------------------------- running it
async def run_agent(question: str, permission_mode: str = "dontAsk"):
    """Yield every message the SDK's loop produces.

    This is the whole "running the agent" story. One `async for`. The loop --
    send, check, run the tool, feed the result back, repeat -- happens inside
    query(). We only read what comes out.
    """
    async for message in query(prompt=question, options=build_options(permission_mode)):
        yield message


# ---------------------------------------------------------------- run it here
# agent_sdk_streamlit.py is the real demo, but this file still runs on its own -- handy as a
# fallback if the browser or Streamlit misbehaves mid-session:
#
#     uv run agent_sdk_teaching.py
#
# Note what is NOT below: no loop. Just `async for` over what the SDK yields.
if __name__ == "__main__":
    import asyncio

    from claude_agent_sdk.types import (
        AssistantMessage,
        ResultMessage,
        SystemMessage,
        TextBlock,
        ToolUseBlock,
    )

    # Deliberately needs two different tools, to show the agent choosing.
    QUESTION = "Who placed order 1001, and how much was it worth?"

    async def main() -> None:
        print(f"Question: {QUESTION}\n")
        async for message in run_agent(QUESTION):
            if isinstance(message, SystemMessage) and message.subtype == "init":
                skills = (message.data or {}).get("skills", [])
                print(f"Skill 'order-support' loaded: {'order-support' in skills}")

            elif isinstance(message, AssistantMessage):
                for block in message.content or []:
                    if isinstance(block, ToolUseBlock) and block.name.startswith("mcp__"):
                        # The agent chose this. We never routed it.
                        short = block.name.replace("mcp__orders__", "")
                        print(f"    [tool] {short}({block.input})")
                    elif isinstance(block, TextBlock) and block.text.strip():
                        if "Base directory for this skill" in block.text:
                            continue  # SKILL.md being read back; not the answer
                        print(f"\nClaude: {block.text.strip()}")

            elif isinstance(message, ResultMessage):
                print(
                    f"\nFinished in {message.num_turns} turn(s). "
                    f"terminal_reason: {message.terminal_reason}"
                )

    asyncio.run(main())
