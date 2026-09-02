"""
agent_mcp_streamlit.py -- Day 18 live demo: the Agent SDK meets MCP.

Run it:
    cd d18
    uv run streamlit run agent_mcp_streamlit.py

The agent lives in agent_mcp_teaching.py. This file only runs it and shows it.
The white theme is pinned in .streamlit/config.toml so the demo looks the same
on every machine.
"""

import asyncio
import json
import os
import time
import urllib.request

import streamlit as st

import agent_mcp_teaching as agent
from claude_agent_sdk.types import (
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

st.set_page_config(page_title="D18 - Agent SDK + MCP", page_icon="*", layout="wide")

# A light, high-contrast look for projecting. Keeps tool cards readable from
# the back of a room.
st.markdown(
    """
    <style>
      .stApp { background: #FFFFFF; }
      .tool-card {
          border: 1px solid #E2E0DB; border-left: 4px solid #C1553B;
          border-radius: 6px; padding: 10px 14px; margin-bottom: 8px;
          background: #FFFFFF;
      }
      .tool-card.off { border-left-color: #D8D5CF; background: #FAFAF9; }
      .tool-name { font-family: Consolas, monospace; font-weight: 700;
                   color: #1F2328; font-size: 0.95rem; }
      .tool-card.off .tool-name { color: #8A8A85; }
      .tool-desc { color: #55585D; font-size: 0.82rem; margin-top: 3px; }
      .pill { display:inline-block; padding: 1px 8px; border-radius: 10px;
              font-size: 0.68rem; font-weight: 700; margin-left: 6px; }
      .pill-on  { background: #DCFCE7; color: #15803D; }
      .pill-off { background: #F1F0EE; color: #8A8A85; }
      .pill-used{ background: #FEF3C7; color: #B45309; }

      /* Sidebar: bigger, darker, bolder -- readable when projected. */
      section[data-testid="stSidebar"] { background: #F7F6F3; }
      section[data-testid="stSidebar"] * { color: #1F2328; }
      section[data-testid="stSidebar"] p,
      section[data-testid="stSidebar"] li {
          font-size: 0.95rem; font-weight: 600;
      }
      section[data-testid="stSidebar"] h3 {
          font-size: 1.05rem; font-weight: 800; letter-spacing: .01em;
      }
      /* the small grey caption lines */
      section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {
          color: #1F2328 !important; font-size: 0.88rem; font-weight: 600;
      }
      section[data-testid="stSidebar"] code {
          color: #1F2328; font-weight: 700; font-size: 0.86rem;
          background: #EDEBE6; padding: 1px 5px; border-radius: 3px;
      }
      /* the id rows */
      .cfg { margin: 5px 0; line-height: 1.35; }
      .cfg-k { font-size: .72rem; font-weight: 800; letter-spacing: .07em;
               text-transform: uppercase; color: #6B7280; }
      .cfg-v { font-family: Consolas, monospace; font-size: .88rem;
               font-weight: 700; color: #1F2328; word-break: break-all; }
      .cost-box { border: 1px solid #E2E0DB; border-left: 4px solid #C1553B;
                  border-radius: 6px; padding: 10px 12px; background: #FFFFFF; }
      .cost-big { font-size: 1.55rem; font-weight: 800; color: #C1553B;
                  line-height: 1.1; }
      .cost-sub { font-size: .78rem; font-weight: 700; color: #6B7280; }
    </style>
    """,
    unsafe_allow_html=True,
)

AGENT_FILE = os.path.join(agent.HERE, "agent_mcp_teaching.py")


# ------------------------------------------------------------------ helpers
@st.cache_data
def agent_source() -> list:
    with open(AGENT_FILE, encoding="utf-8") as f:
        return f.read().splitlines()


def find_line(needle: str) -> int:
    for i, line in enumerate(agent_source(), start=1):
        if needle in line:
            return i
    return 0


def show_lines(first: int, last: int) -> None:
    lines = agent_source()[first - 1 : last]
    body = "\n".join(f"{first + i:>4} | {line}" for i, line in enumerate(lines))
    st.code(body, language="python")


L_START = find_line("=== MCP SETUP : START ===")
L_END = find_line("=== MCP SETUP : END ===")
L_CONNECT = find_line("MCP_SERVERS = {")
L_RESTRICT = find_line("AIRTABLE_TOOLS = [")
L_OPTS = find_line("def build_options")
L_RUN = find_line("async def run_agent")
L_MCPLINE = find_line("mcp_servers=MCP_SERVERS")


def mcp_rpc(method: str, params=None):
    """One JSON-RPC call to the MCP server. This is the protocol, unwrapped."""
    body = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        body["params"] = params
    headers = {
        "Authorization": f"Bearer {agent.AIRTABLE_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    req = urllib.request.Request(
        agent.AIRTABLE_MCP_URL, data=json.dumps(body).encode(), headers=headers
    )
    raw = urllib.request.urlopen(req, timeout=30).read().decode()
    text = raw
    for line in raw.splitlines():          # the server answers as SSE
        if line.startswith("data: "):
            text = line[6:]
    return json.loads(text)


@st.cache_data(show_spinner=False)
def probe_server() -> dict:
    """Ask the server for all three primitives: tools, resources, prompts."""
    out = {"ok": False, "tools": [], "resources": [], "prompts": None,
           "capabilities": {}, "info": {}, "protocol": "", "error": ""}
    try:
        init = mcp_rpc("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "d18-demo", "version": "1"},
        }).get("result", {})
        out["capabilities"] = init.get("capabilities", {})
        out["info"] = init.get("serverInfo", {})
        out["protocol"] = init.get("protocolVersion", "")

        out["tools"] = mcp_rpc("tools/list", {}).get("result", {}).get("tools", [])

        res = mcp_rpc("resources/list", {})
        out["resources"] = res.get("result", {}).get("resources", [])

        pr = mcp_rpc("prompts/list", {})
        # A server that does not implement prompts answers "Method not found".
        out["prompts"] = (
            None if "error" in pr else pr.get("result", {}).get("prompts", [])
        )
        out["ok"] = True
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def tool_card(name: str, desc: str, allowed: bool, used: bool = False) -> str:
    pill = '<span class="pill pill-on">ALLOWED</span>' if allowed else \
           '<span class="pill pill-off">not allowed</span>'
    if used:
        pill += '<span class="pill pill-used">USED THIS RUN</span>'
    cls = "tool-card" if allowed else "tool-card off"
    return (
        f'<div class="{cls}"><span class="tool-name">{name}</span>{pill}'
        f'<div class="tool-desc">{(desc or "")[:150]}</div></div>'
    )


# ------------------------------------------------------------------ header
st.title("The Agent SDK meets MCP")
st.caption(
    f"Day 18 live demo . the MCP setup is in **agent_mcp_teaching.py**, "
    f"lines **{L_START}-{L_END}** . this file just runs it"
)

with st.sidebar:
    st.markdown("### The one idea")
    st.markdown(
        "**Day 17** you wrote a tool and the SDK called it.\n\n"
        "**Day 18** the tools are not yours. They live on Airtable's server "
        "and you connect to it."
    )
    st.divider()

    # --- what this run has cost ---------------------------------------
    # Every agent run adds to this; it survives reruns via session_state.
    st.markdown("### Cost this session")
    # A placeholder, so a run finishing can rewrite this in place rather than
    # leaving the sidebar a rerun behind.
    COST_SLOT = st.empty()
    AVG_SLOT = st.empty()

    def paint_cost() -> None:
        sp = st.session_state.get("spend", {"usd": 0.0, "runs": 0, "calls": 0})
        COST_SLOT.markdown(
            f'<div class="cost-box">'
            f'<div class="cost-big">${sp["usd"]:.4f}</div>'
            f'<div class="cost-sub">{sp["runs"]} run(s) . '
            f'{sp["calls"]} Airtable call(s)</div></div>',
            unsafe_allow_html=True,
        )
        AVG_SLOT.caption(
            f"average ${sp['usd'] / sp['runs']:.4f} per question" if sp["runs"] else ""
        )

    paint_cost()
    if st.button("Reset cost", width="stretch"):
        st.session_state["spend"] = {"usd": 0.0, "runs": 0, "calls": 0}
        st.rerun()

    st.divider()
    st.markdown("### This connection")
    st.caption("all from `.env` - nothing hard-coded")

    def cfg(label: str, value: str) -> None:
        st.markdown(
            f'<div class="cfg"><div class="cfg-k">{label}</div>'
            f'<div class="cfg-v">{value}</div></div>',
            unsafe_allow_html=True,
        )

    cfg("MCP server", agent.AIRTABLE_MCP_URL)
    cfg("Base ID", agent.BASE_ID or "MISSING")
    cfg("Customers table", agent.CUSTOMERS_TABLE or "MISSING")
    cfg("Orders table", agent.ORDERS_TABLE or "MISSING")
    cfg("Token", f"{agent.AIRTABLE_TOKEN[:10]}..." if agent.AIRTABLE_TOKEN else "MISSING")
    cfg("Model", agent.MODEL)

tab_run, tab_tools, tab_prims, tab_connect, tab_exam = st.tabs([
    "1 . Run the agent",
    "2 . The 43 tools, and the 4 we use",
    "3 . MCP primitives & how to define them",
    "4 . How it connects",
    "5 . Exam concepts, in this code",
])


# ============================================================ TAB 1 : RUN IT
with tab_run:
    st.subheader("Ask it something. The answer comes from a real Airtable base.")

    question = st.text_input(
        "Customer question",
        value="What's the status of order ORD1005? Give the status, product and ship date.",
    )
    c1, c2 = st.columns([1, 2])
    with c1:
        go = st.button("Run the agent", type="primary", width="stretch")
    with c2:
        st.caption(
            "Try: *who is priya.patel@email.com?* . *which orders are delayed?* . "
            "*delete the Orders table* (not in the allow-list, so it cannot)"
        )

    # The allow-list, always on screen, lighting up as tools get used.
    st.markdown("**The four tools this agent may call** - out of the server's 43:")
    slots = {name: st.empty() for name in agent.AIRTABLE_TOOLS}
    for name, slot in slots.items():
        slot.markdown(tool_card(f"mcp__airtable__{name}", "", True), unsafe_allow_html=True)

    if go:
        stats = {"messages": 0, "tool_calls": 0, "tools_used": []}
        transcript = st.container()
        raw_log = []
        started = time.time()

        def render(message):
            stats["messages"] += 1
            raw_log.append(f"----- {type(message).__name__} -----\n{message!r}")

            if isinstance(message, SystemMessage) and message.subtype == "init":
                servers = (message.data or {}).get("mcp_servers", [])
                with transcript:
                    st.success(
                        f"Connected to the MCP server -> `{servers}`. "
                        "Everything below uses tools you did not write."
                    )

            elif isinstance(message, (AssistantMessage, UserMessage)):
                if isinstance(message.content, str):
                    return
                for block in message.content or []:
                    if isinstance(block, ToolUseBlock):
                        short = block.name.split("__")[-1]
                        if block.name.startswith("mcp__"):
                            stats["tool_calls"] += 1
                            if short not in stats["tools_used"]:
                                stats["tools_used"].append(short)
                            if short in slots:      # light up the card above
                                slots[short].markdown(
                                    tool_card(f"mcp__airtable__{short}", "", True, used=True),
                                    unsafe_allow_html=True,
                                )
                            with transcript:
                                st.info(
                                    f"**The agent called Airtable's `{short}` tool**\n\n"
                                    f"`{json.dumps(block.input)[:300]}`\n\n"
                                    "You did not write this tool. It lives on "
                                    "Airtable's server; the SDK discovered it, "
                                    "called it, and will feed the result back."
                                )
                        else:
                            with transcript:
                                st.caption(
                                    f"harness tool: {short} "
                                    "(finding the right Airtable tool among 43)"
                                )

                    elif isinstance(block, ToolResultBlock):
                        with transcript:
                            with st.expander("raw record returned by Airtable"):
                                st.code(str(block.content)[:2000], language="json")

                    elif isinstance(block, TextBlock) and block.text.strip():
                        with transcript:
                            st.markdown(f"**Claude:** {block.text}")

            elif isinstance(message, ResultMessage):
                # Roll this run into the sidebar's running total.
                tally = st.session_state.get(
                    "spend", {"usd": 0.0, "runs": 0, "calls": 0}
                )
                tally["usd"] += message.total_cost_usd or 0.0
                tally["runs"] += 1
                tally["calls"] += stats["tool_calls"]
                st.session_state["spend"] = tally
                paint_cost()          # update the sidebar without a rerun

                with transcript:
                    st.divider()
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("SDK messages", stats["messages"])
                    m2.metric("Turns", message.num_turns)
                    m3.metric("Airtable calls", stats["tool_calls"])
                    m4.metric(
                        "Cost",
                        f"${message.total_cost_usd:.4f}" if message.total_cost_usd else "n/a",
                    )
                    if stats["tools_used"]:
                        used = ", ".join(f"`{t}`" for t in stats["tools_used"])
                        st.caption(
                            f"Borrowed from the MCP server this run: {used} - "
                            f"{len(stats['tools_used'])} of the 4 allowed, "
                            "out of 43 the server offers."
                        )
                    st.caption(
                        f"terminal_reason: `{message.terminal_reason}` . "
                        f"{time.time() - started:.1f}s . "
                        "the loop was the SDK's, and the tools were Airtable's"
                    )

        async def main():
            async for message in agent.run_agent(question):
                render(message)

        try:
            with st.spinner("Connecting to Airtable and running the loop..."):
                asyncio.run(main())
        except Exception as exc:
            low = str(exc).lower()
            if "credit balance" in low:
                st.error("**The Anthropic API key has no credit.** Top it up and re-run.")
            elif "401" in low or "unauthor" in low or "forbidden" in low:
                st.error(
                    "**Airtable rejected the token.** Check AIRTABLE_MCP_TOKEN in .env "
                    "and its scopes (schema.bases:read, data.records:read)."
                )
            else:
                st.error(f"{type(exc).__name__}: {exc}")

        with st.expander("Raw message stream"):
            st.code("\n\n".join(raw_log) or "(nothing)", language="text")


# ================================================ TAB 2 : THE TOOLS BROWSER
with tab_tools:
    st.subheader("Everything the server offers, and the four we borrow")
    st.markdown(
        "Connecting to an MCP server does not give you a tidy little helper. "
        "Airtable's server offers **43 tools** - including ones that delete "
        "records and drop tables. Your agent gets all of them unless you say "
        "otherwise."
    )

    if st.button("Load the server's tool catalogue", type="primary", key="load_tools"):
        st.session_state["probe"] = probe_server()

    data = st.session_state.get("probe")
    if not data:
        st.info("Click the button to ask the live server what it can do.")
    elif not data["ok"]:
        st.error(f"Could not reach the server: {data['error']}")
    else:
        tools = data["tools"]
        allowed = list(agent.AIRTABLE_TOOLS)

        a, b, c = st.columns(3)
        a.metric("Tools the server offers", len(tools))
        b.metric("Tools we allow", len(allowed))
        c.metric("Tools we blocked", len(tools) - len(allowed))
        st.caption(
            "Discovery decides what is POSSIBLE. The allow-list decides what "
            "is PERMITTED. Two different jobs - you need both."
        )

        st.divider()
        left, right = st.columns(2)

        with left:
            st.markdown("#### The 4 we borrow")
            st.caption("named in `allowed_tools` -> these run without asking")
            by_name = {t["name"]: t.get("description", "") for t in tools}
            for name in allowed:
                st.markdown(
                    tool_card(name, by_name.get(name, "(not offered by this server)"), True),
                    unsafe_allow_html=True,
                )
            st.markdown("**Why these four**")
            st.markdown(
                "- `search_records` - answers almost every question in one call\n"
                "- `list_records_for_table` - browse a whole table\n"
                "- `get_table_schema` - field names and types\n"
                "- `update_records_for_table` - the single write path, for refunds"
            )

        with right:
            st.markdown("#### The other 39")
            st.caption("discovered, catalogued - and not callable by this agent")
            show_all = st.checkbox("show all of them", value=False)
            others = [t for t in tools if t["name"] not in allowed]
            danger_words = ("delete", "create_base", "drop")
            risky = [t for t in others if any(w in t["name"] for w in danger_words)]

            st.markdown(f"**{len(risky)} of them are destructive:**")
            for t in risky[:6]:
                st.markdown(
                    tool_card(t["name"], t.get("description", ""), False),
                    unsafe_allow_html=True,
                )
            if show_all:
                for t in others:
                    if t in risky[:6]:
                        continue
                    st.markdown(
                        tool_card(t["name"], t.get("description", ""), False),
                        unsafe_allow_html=True,
                    )

        st.divider()
        st.markdown("#### The raw schema the agent reads to choose a tool")
        names = [t["name"] for t in tools]
        pick = st.selectbox(
            "Inspect any tool the server offers",
            names,
            index=names.index("search_records") if "search_records" in names else 0,
        )
        chosen = next(t for t in tools if t["name"] == pick)
        st.code(json.dumps(chosen, indent=2)[:3000], language="json")
        st.caption(
            "The **description** is prompt text - it is how the agent decides "
            "when to call this. The **inputSchema** is what its arguments are "
            "validated against. Exactly like the `@tool` decorator in Day 17, "
            "except Airtable wrote it, not you."
        )


# ============================================== TAB 3 : THE MCP PRIMITIVES
with tab_prims:
    st.subheader("The three primitives - what they are, and how each one is defined")
    st.markdown(
        "An MCP server can offer three kinds of thing. Pick one to see how it "
        "is written in code, then ask the live server whether it offers any."
    )

    primitive = st.radio(
        "Primitive",
        ["Tools", "Resources", "Prompts"],
        horizontal=True,
        key="which_primitive",
    )

    # --- what it is -----------------------------------------------------
    facts = {
        "Tools": (
            "**model**-controlled",
            "Things the agent can **do**. The agent decides when to call one, "
            "by reading its description.",
            "`search_records`, `update_records_for_table`, `delete_table`",
        ),
        "Resources": (
            "**application**-controlled",
            "Things the agent can **read**. Your code decides what to attach, "
            "and each one is addressed by a URI. Data, not a verb.",
            "`file:///logs/today.log`, `airtable://base/tblX/recY`",
        ),
        "Prompts": (
            "**user**-controlled",
            "Reusable prompt templates the server offers. A person picks one "
            "from a menu - Claude Code shows them as slash commands.",
            "`/review-pr`, `/summarise-ticket`",
        ),
    }
    who, what, examples = facts[primitive]
    f1, f2 = st.columns([1, 2])
    f1.metric("Controlled by", who.replace("**", ""))
    f2.markdown(f"{what}\n\nExamples: {examples}")

    st.divider()

    # --- how it is defined ----------------------------------------------
    st.markdown(f"#### Defining a {primitive[:-1].lower()} - server side")
    st.caption(
        "This is what the person WRITING an MCP server does. Airtable wrote "
        "the equivalent of this; you are on the client side of it."
    )

    snippets = {
        "Tools": (
            'from mcp.server.mcpserver import MCPServer\n'
            '\n'
            'server = MCPServer("support-desk")\n'
            '\n'
            '@server.tool()                      # <-- the decorator\n'
            'def get_order_status(order_id: str) -> dict:\n'
            '    """Look up an order\'s shipping status."""\n'
            '    return {"status": "Processing", "carrier": "BlueDart"}\n'
            '\n'
            '# The docstring becomes the description the agent reads.\n'
            '# The type hints become the inputSchema it is validated against.'
        ),
        "Resources": (
            'from mcp.server.mcpserver import MCPServer\n'
            '\n'
            'server = MCPServer("support-desk")\n'
            '\n'
            '@server.resource("orders://{order_id}")   # <-- a URI template\n'
            'def order_record(order_id: str) -> str:\n'
            '    """The raw record for one order."""\n'
            '    return open(f"orders/{order_id}.json").read()\n'
            '\n'
            '# Addressed by URI, not called like a function.\n'
            '# The APPLICATION decides to attach it; the model does not\n'
            '# choose to "call" a resource the way it calls a tool.'
        ),
        "Prompts": (
            'from mcp.server.mcpserver import MCPServer\n'
            '\n'
            'server = MCPServer("support-desk")\n'
            '\n'
            '@server.prompt()                    # <-- a reusable template\n'
            'def refund_review(order_id: str) -> str:\n'
            '    """Walk through whether an order qualifies for a refund."""\n'
            '    return (\n'
            '        f"Check order {order_id}. Confirm Refund Eligible is "\n'
            '        f"ticked, then summarise in two lines."\n'
            '    )\n'
            '\n'
            '# A PERSON picks this from a menu. In Claude Code a server\'s\n'
            '# prompts appear as slash commands.'
        ),
    }
    st.code(snippets[primitive], language="python")

    if primitive == "Tools":
        st.markdown(
            "**In this project**, the client side of that is "
            f"`agent_mcp_teaching.py` line **{L_RESTRICT}** - you name which of "
            "the server's tools you will allow:"
        )
        show_lines(L_RESTRICT, L_RESTRICT + 6)
    else:
        st.info(
            f"**This demo does not use {primitive.lower()}.** Airtable's server "
            f"offers none, so there is nothing in `agent_mcp_teaching.py` to "
            f"point at. The snippet above is how you would define one if you "
            f"were writing the server yourself."
        )

    st.divider()

    # --- ask the live server --------------------------------------------
    st.markdown(f"#### Does the live server offer any {primitive.lower()}?")
    method = {"Tools": "tools/list", "Resources": "resources/list",
              "Prompts": "prompts/list"}[primitive]
    st.code(
        '{"jsonrpc": "2.0", "id": 1, "method": "' + method + '", "params": {}}',
        language="json",
    )
    st.caption(f"The exact JSON-RPC request the button below sends.")

    if st.button(f"Send {method} to the server", type="primary", key="probe_prims"):
        st.session_state["probe"] = probe_server()

    data = st.session_state.get("probe")
    if data and data["ok"]:
        info = data["info"]
        st.success(
            f"Handshake OK - server **{info.get('name','?')}** "
            f"v{info.get('version','?')} . protocol `{data['protocol']}`"
        )

        r1, r2, r3 = st.columns(3)
        r1.metric("Tools", len(data["tools"]))
        r2.metric("Resources", len(data["resources"]))
        r3.metric("Prompts", "not implemented" if data["prompts"] is None
                  else len(data["prompts"]))

        if primitive == "Tools":
            st.markdown(
                f"**{len(data['tools'])} tools came back.** Names, descriptions "
                "and schemas - none of which appear anywhere in our code. "
                "Tab 2 lists them all."
            )
        elif primitive == "Resources":
            st.markdown(
                f"**{len(data['resources'])} resources.** Airtable declares the "
                "`resources` capability but exposes none - you reach its records "
                "through tools instead."
            )
        else:
            st.markdown(
                "**Method not found.** This server does not implement prompts "
                "at all. A server offers only the primitives it needs."
            )

        with st.expander("What the server declared in its capabilities"):
            st.code(json.dumps(data["capabilities"], indent=2), language="json")
            st.caption(
                "Declared at handshake time, before any list call. It advertises "
                "`tools` and `resources`, and says nothing about prompts."
            )
    elif data:
        st.error(f"Could not reach the server: {data['error']}")

    st.divider()
    with st.expander("The handshake every MCP session runs"):
        st.markdown(
            "1. **initialize** - client and server agree a protocol version and "
            "swap capabilities\n"
            "2. **tools/list** (and `resources/list`, `prompts/list`) - discovery\n"
            "3. **tools/call** - the agent actually uses one\n\n"
            "The SDK does all three for you. This tab makes the same calls by "
            "hand so you can watch them happen."
        )
        st.caption("MCP is JSON-RPC underneath. That is the whole wire format.")



# ======================================================= TAB 4 : HOW IT CONNECTS
with tab_connect:
    st.subheader("Four lines of config. That is the whole integration.")
    st.markdown(
        f"The MCP setup is `agent_mcp_teaching.py` lines **{L_START}-{L_END}**. "
        "No Airtable SDK is imported anywhere in this project."
    )

    q1, q2, q3 = st.columns(3)
    q1.metric("Connect", f"line {L_CONNECT}", "the server address")
    q2.metric("Restrict", f"line {L_RESTRICT}", "which tools you allow")
    q3.metric("The one new option", f"line {L_MCPLINE}", "mcp_servers=")

    st.divider()
    piece = st.radio(
        "Show me",
        ["Connect", "Restrict", "The options", "Running it"],
        horizontal=True,
        key="connect_piece",
    )

    if piece == "Connect":
        show_lines(L_CONNECT - 12, L_CONNECT + 8)
        st.markdown(
            "- `type: http` is the **transport** - a server reached over the "
            "network. A server on your own machine would be `stdio`: same "
            "protocol, different pipe.\n"
            "- `airtable` is just a local nickname. It becomes the tool prefix "
            "`mcp__airtable__...`.\n"
            "- The URL and token come from `.env`. Point them at a different "
            "MCP server and this same agent has different powers."
        )

    elif piece == "Restrict":
        show_lines(L_RESTRICT - 8, L_RESTRICT + 12)
        st.markdown(
            "Four tools out of 43. **Discovery decides what is possible; the "
            "allow-list decides what is permitted.**"
        )

    elif piece == "The options":
        show_lines(L_OPTS, L_END - 2)
        st.success(
            "The same `ClaudeAgentOptions` object as Day 17. The only "
            "genuinely new line is `mcp_servers=`."
        )
        st.warning(
            "**The trap in this file:** the obvious way to drop the built-in "
            "tools is `tools=[]`. Do that and the MCP tools disappear too - the "
            "agent connects, receives zero tools, and then invents a "
            "confident-sounding answer. Deny the built-ins by name instead."
        )

    else:
        show_lines(L_RUN - 1, L_RUN + 11)
        st.success(
            "Connecting to a remote tool server changed what the agent can DO, "
            "not how you run it. Still one `async for`, exactly like Day 17."
        )


# ==================================================== TAB 5 : EXAM CONCEPTS
with tab_exam:
    st.subheader("Where each MCP concept lives in this code")
    st.caption("Every row points at a real line in agent_mcp_teaching.py.")

    rows = [
        ("What MCP is", f"line {L_CONNECT}",
         "Model Context Protocol: one standard way for an agent to talk to a "
         "tool server. Because it is a standard, these same four lines work for "
         "any MCP server - Airtable, GitHub, a database, one you write."),
        ("The three primitives", "tab 3",
         "**Tools** (model-controlled - things to DO), **Resources** "
         "(application-controlled - things to READ, by URI), **Prompts** "
         "(user-controlled - templates, surfaced as slash commands). Airtable "
         "implements tools; it declares resources but exposes none, and does "
         "not implement prompts at all."),
        ("Client vs server", f"line {L_CONNECT}",
         "Airtable runs the **server**. Your agent is the **client**. You wrote "
         "none of these 43 tools and cannot change them - you connect and use "
         "what is offered."),
        ("Transport: http vs stdio", f"line {L_CONNECT + 2}",
         "`http` reaches a server across the network, as here. `stdio` launches "
         "a server as a local subprocess and talks over pipes. Same protocol, "
         "same tool calls - only the plumbing differs."),
        ("Discovery", f"line {L_RESTRICT}",
         "Nothing in the code lists Airtable's tools. On connect the server "
         "sends its catalogue - names, descriptions, schemas. Tab 2 shows the "
         "real catalogue arriving."),
        ("The handshake", "tab 3",
         "`initialize` (agree a version, swap capabilities) -> `tools/list` "
         "(discovery) -> `tools/call` (use one). MCP is JSON-RPC underneath."),
        ("The tool prefix", f"line {find_line('ALLOWED_TOOLS = ')}",
         "`mcp__airtable__search_records`: `mcp__` marks it as coming from a "
         "server, and `airtable` is the nickname from your config. That is how "
         "the SDK routes the call."),
        ("allowed_tools", f"line {find_line('allowed_tools=ALLOWED_TOOLS')}",
         "Four of 43. Discovery decides what is possible; this decides what is "
         "permitted. Naming them also skips the search the harness would "
         "otherwise do."),
        ("The tools=[] trap", f"line {find_line('disallowed_tools=[')}",
         "`tools=[]` looks like the way to drop built-in tools - but it drops "
         "the MCP tools too, and the agent then invents an answer instead of "
         "reading Airtable. Deny built-ins by name."),
        ("permission_mode", f"line {find_line('permission_mode=permission_mode')}",
         "A script has nobody to answer a prompt. Without a mode that decides "
         "on its own, every Airtable call comes back permission_denied."),
        ("Auth is the real boundary", f"line {find_line('AIRTABLE_TOKEN =')}",
         "MCP adds no permissions of its own. The agent can do exactly what the "
         "token can do, so scope the token in Airtable - that limit survives "
         "any mistake in the prompt or the allow-list."),
        ("Config, not code", f"line {find_line('BASE_ID = os.environ')}",
         "The server URL, base and table IDs all come from `.env`. Pointing the "
         "demo at a different base is a config change, not an edit."),
        ("The loop is unchanged", f"line {L_RUN}",
         "One `async for`, same as Day 17. MCP changed what the agent can "
         "reach, not who runs the loop."),
    ]

    for topic, where, detail in rows:
        with st.expander(f"**{topic}**  .  {where}"):
            st.markdown(detail)

    st.divider()
    st.markdown("#### Day 17 vs Day 18, in one table")
    st.markdown(
        "| | Day 17 - your own tool | Day 18 - an MCP server |\n"
        "|---|---|---|\n"
        "| **Who wrote the tool** | you did | Airtable did |\n"
        "| **Where it runs** | in your Python process | on Airtable's servers |\n"
        "| **How it is defined** | `@tool` decorator | the server's own schema |\n"
        "| **How many tools** | the 3 you wrote | 43, discovered on connect |\n"
        "| **How you connect** | `create_sdk_mcp_server(...)` | a URL and a token |\n"
        "| **Who limits it** | you wrote the function | your allow-list + your token |\n"
        "| **Who runs the loop** | the SDK | the SDK - unchanged |"
    )
    st.caption(
        "The last row is the point. MCP changes what an agent can reach. "
        "It does not change how you build or run one."
    )
