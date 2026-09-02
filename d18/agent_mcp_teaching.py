"""
agent_mcp_teaching.py -- Day 18: the Agent SDK meets MCP.

This file is the thing being demonstrated. agent_mcp_streamlit.py only reads it
and displays it. Everything that makes this an MCP agent lives between the two
MCP SETUP banner comments below; the Streamlit app finds those banners and puts
their real line numbers on screen.

THE ONE IDEA
    Day 17: you wrote a tool, and the SDK called it. Your tool, your process.
    Day 18: the tools are NOT yours. They live on someone else's server --
            Airtable's -- and you connect to it. You wrote none of them.

    That is MCP. A tool your agent uses but does not own.

WHAT MCP ACTUALLY IS
    Model Context Protocol: one standard way for an agent to talk to a tool
    server. Because it is a standard, the same four lines of config work for
    ANY MCP server -- Airtable, GitHub, a database, one you write yourself.
    Swap the URL and the agent has different powers. Nothing else changes.

WHAT THIS AGENT DOES
    It is a customer-support agent for a real Airtable base called
    "Support Desk", with two tables:

        Customers   Customer ID, Name, Email, Tier, Account Status
        Orders      Order ID, Product, Status, Ship Date, Amount,
                    Refund Eligible, Customer ID

    Ask it "what's the status of ORD1005?" and it reaches across the network
    into a real Airtable base and answers from the actual row.

    The records are REAL. Edit the base in your browser, ask again, and the
    answer changes -- there is no fixture file anywhere in this project.

THE THREE MCP PRIMITIVES
    A server can offer three kinds of thing. The names matter -- they are
    what the spec calls them, and what an exam will ask about:

      TOOLS      things the agent can DO. Model-controlled: the agent decides
                 when to call one. Airtable offers 43 (search_records,
                 update_records_for_table, delete_table...). This is the
                 primitive nearly every server leads with, and the only one
                 this demo actually uses.

      RESOURCES  things the agent can READ. Application-controlled: your code
                 chooses what to attach, like a file or a record, addressed by
                 URI. Closer to context than to an action.

      PROMPTS    reusable prompt templates the server offers. User-controlled:
                 a person picks one, typically from a menu -- Claude Code
                 surfaces them as slash commands.

    Airtable's server declares tools and resources, exposes 43 tools and 0
    resources, and does not implement prompts at all. Tab 3 of the demo asks
    the live server for all three and shows exactly that. A server implements
    only what it needs.

THE FOUR THINGS TO SHOW STUDENTS
    1. CONNECT    -- four lines of config, and the agent has 43 new tools
    2. DISCOVER   -- you never listed the tools; the server told the agent
    3. RESTRICT   -- an allow-list, because 43 tools is 43 ways to go wrong
    4. RUN        -- one `async for`. The SDK still owns the loop.
"""

import asyncio
import os

from dotenv import load_dotenv

# THE RENAME TRAP (Day 17, slide 11): the package is claude_agent_sdk.
# claude_code_sdk / ClaudeCodeOptions are the deprecated names and will not import.
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

HERE = os.path.dirname(os.path.abspath(__file__))

# Pinned. No fallback to a bigger model behind your back.
MODEL = "claude-haiku-4-5-20251001"

# The spend cap. A remote server can be slow, and every retry costs a turn.
MAX_TURNS = 8


#  ======================================================================
#  === MCP SETUP : START ================================================
#  Everything from here to the END banner is what makes this an MCP agent.
#     1. CONNECT   -- point at the server
#     2. RESTRICT  -- choose which of its tools you will allow
#     3. BRIEF     -- tell the agent what it is for
#     4. OPTIONS   -- hand all of it to the SDK
#  ======================================================================

# --- 1. CONNECT --------------------------------------------------------
# The address of a tool server that already exists. Airtable runs it; we are
# only a client. This is the entire "integration" -- a URL and a token.
#
# Both come from .env, not from this file. Point AIRTABLE_MCP_URL at a
# different MCP server and this same agent has different powers, with no code
# change at all. That is what "a standard protocol" buys you.
AIRTABLE_MCP_URL = os.environ.get("AIRTABLE_MCP_URL", "https://mcp.airtable.com/mcp")

# The token is the agent's Airtable identity. Scope it in Airtable to exactly
# what the agent should reach -- MCP does not add permissions of its own, it
# inherits whatever this token can already do.
AIRTABLE_TOKEN = os.environ.get("AIRTABLE_MCP_TOKEN", "")

# THE FOUR LINES THAT ADD 43 TOOLS.
# "airtable" is our local nickname for the server; it becomes the tool prefix
# mcp__airtable__<tool>. "http" is the transport -- a remote server reached over
# the network. (A server on your own machine would be "stdio" instead. Same
# protocol, different pipe.)
MCP_SERVERS = {
    "airtable": {
        "type": "http",
        "url": AIRTABLE_MCP_URL,
    }
}


# --- 2. RESTRICT -------------------------------------------------------
# DISCOVERY: we never told the agent what Airtable can do. On connect, the
# server hands over its whole catalogue -- 43 tools, with names, descriptions
# and schemas. That is the protocol doing the work.
#
# But 43 tools is 43 ways to go wrong, and this server can delete records. So
# we allow four, and the rest may as well not exist. Discovery decides what is
# POSSIBLE; the allow-list decides what is PERMITTED.
AIRTABLE_TOOLS = [
    "search_records",            # keyword search -- answers almost everything
    "list_records_for_table",    # browse a table  # the one write path: noting a refund
]

# The allow-list needs each tool's fully-qualified name: mcp__<server>__<tool>.
# The "airtable" here is the nickname from MCP_SERVERS above.
ALLOWED_TOOLS = [f"mcp__airtable__{name}" for name in AIRTABLE_TOOLS]


# --- 3. BRIEF ----------------------------------------------------------
# Pinned IDs. Without them the agent burns turns on discovery: search_bases ->
# list_tables -> then finally the lookup. Three round trips for one question.
# Telling it where to look is most of the difference between a slow demo and a
# fast one.
# From .env, so pointing the demo at a different Airtable base is a config
# change and nothing else. No IDs are hard-coded in this file.
BASE_ID = os.environ.get("AIRTABLE_BASE_ID", "")
CUSTOMERS_TABLE = os.environ.get("AIRTABLE_CUSTOMERS_TABLE", "")
ORDERS_TABLE = os.environ.get("AIRTABLE_ORDERS_TABLE", "")

SYSTEM_PROMPT = f"""You are a customer-support agent for the "Support Desk" Airtable base.
You reach real records through the Airtable MCP server.

The base and tables are already known -- use these IDs directly, and never call
search_bases or list_bases:
    baseId          = {BASE_ID}
    Customers table = {CUSTOMERS_TABLE}
    Orders table    = {ORDERS_TABLE}

USE ONE TOOL CALL WHERE YOU CAN. A keyword query through search_records against
the right table answers almost every question: a customer by email, an order by
its ID, which orders are delayed. Call it once and answer from what came back.
Do not chain a second lookup just to confirm the first.

Ask for every field you might need in that ONE call, or you will be missing data
you then cannot report:
    Orders    -> Order ID, Product, Status, Ship Date, Amount, Refund Eligible, Customer ID
    Customers -> Customer ID, Name, Email, Tier, Account Status

Rules:
  - Answer only from records you actually retrieved. If nothing is found, say so.
  - Check Refund Eligible before noting any refund.
  - If an order is Delayed, or an account is Suspended, or the request is outside
    these abilities, escalate to a human instead of deciding alone.
  - Keep replies short and plain.
"""


# --- 4. OPTIONS --------------------------------------------------------
# The same ClaudeAgentOptions object as Day 17. The ONLY new field is
# mcp_servers. Everything else you already know.
def build_options(permission_mode: str = "bypassPermissions") -> ClaudeAgentOptions:
    """The agent's control panel. permission_mode is a parameter only so the
    demo can flip it live; in real code you would hard-code one."""
    return ClaudeAgentOptions(
        model=MODEL,
        fallback_model=MODEL,
        system_prompt=SYSTEM_PROMPT,
        # <<< THE MCP LINE. Everything else here is ordinary Day 17 config. >>>
        mcp_servers=MCP_SERVERS,
        # Only the four Airtable tools run without asking.
        allowed_tools=ALLOWED_TOOLS,
        # Hard blocks on the built-ins, so this agent can reach Airtable and
        # nothing else -- it has no business touching the filesystem or shell.
        #
        # A TRAP WORTH SHOWING: the obvious way to write this is `tools=[]`
        # ("disable all built-in tools"). Do that and the MCP tools vanish too
        # -- the agent connects, gets zero tools, and then INVENTS an answer
        # that looks perfectly plausible. Deny the built-ins by name instead.
        #
        # ToolSearch is deliberately NOT denied. The harness uses it to find
        # the right Airtable tool among the server's 43, and blocking it makes
        # the agent flail and cost MORE, not less.
        disallowed_tools=[
            "Bash", "Write", "Edit", "Read", "Glob", "Grep",
            "WebSearch", "WebFetch", "Task",
        ],
        # A script has nobody to answer a permission prompt. Without a mode that
        # decides on its own, every tool call would come back permission_denied.
        permission_mode=permission_mode,
        max_turns=MAX_TURNS,
        cwd=HERE,
        setting_sources=["user"],
    )


#  === MCP SETUP : END ==================================================
#  ======================================================================


# ---------------------------------------------------------------- running it
async def run_agent(question: str, permission_mode: str = "bypassPermissions"):
    """Yield every message the SDK's loop produces.

    Look at how little is here. Connecting to a remote tool server changed the
    agent's ABILITIES, not the way you run it -- this is the same single
    `async for` as Day 17. The SDK still owns the loop: it discovers the
    server's tools, calls them, feeds results back, and repeats.
    """
    async for message in query(prompt=question, options=build_options(permission_mode)):
        yield message


# ---------------------------------------------------------------- run it here
# agent_mcp_streamlit.py is the real demo, but this file runs on its own too --
# handy as a fallback if the browser misbehaves mid-session:
#
#     uv run agent_mcp_teaching.py
if __name__ == "__main__":
    QUESTION = (
        "What's the status of order ORD1005? "
        "Give the status, the product and the ship date."
    )

    async def main() -> None:
        print(f"Question: {QUESTION}\n")
        async for message in run_agent(QUESTION):
            if isinstance(message, SystemMessage) and message.subtype == "init":
                # Proof the connection worked: these tool names came from
                # Airtable's server, not from this file.
                tools = [t for t in (message.data or {}).get("tools", []) if "airtable" in t]
                print(f"Connected. Airtable tools available: {len(tools)}")

            elif isinstance(message, (AssistantMessage, UserMessage)):
                if isinstance(message.content, str):
                    continue
                for block in message.content or []:
                    if isinstance(block, ToolUseBlock):
                        short = block.name.split("__")[-1]
                        print(f"    [mcp tool] {short}({block.input})")
                    elif isinstance(block, ToolResultBlock):
                        text = str(block.content)[:160].replace("\n", " ")
                        print(f"    [result]   {text}")
                    elif isinstance(block, TextBlock) and block.text.strip():
                        print(f"\nClaude: {block.text.strip()}")

            elif isinstance(message, ResultMessage):
                print(
                    f"\nFinished in {message.num_turns} turn(s). "
                    f"terminal_reason: {message.terminal_reason} "
                    f"cost: ${message.total_cost_usd or 0:.4f}"
                )

    asyncio.run(main())
