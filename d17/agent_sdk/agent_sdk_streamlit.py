"""
agent_sdk_streamlit.py -- Day 17 live demo: "The Agent SDK -- the loop you no longer write."

Run it:
    cd d17/agent_sdk
    uv run streamlit run agent_sdk_streamlit.py

What this is: a demo you drive, not slides to read. The deck already made the
argument; this shows the argument is true in running code.

The agent itself lives in agent_sdk_teaching.py. This file only runs it and shows it.
"""

import asyncio
import inspect
import json
import os
import re
import time

import streamlit as st

import agent_sdk_teaching
import anthropic_sdk
from claude_agent_sdk.types import (
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

st.set_page_config(page_title="D17 - Agent SDK", page_icon="*", layout="wide")

AGENT_FILE = os.path.join(agent_sdk_teaching.HERE, "agent_sdk_teaching.py")
SKILL_FILE = os.path.join(agent_sdk_teaching.HERE, ".claude", "skills", "order-support", "SKILL.md")


# ------------------------------------------------------------------ helpers
@st.cache_data
def agent_source() -> list:
    """agent_sdk_teaching.py as a list of lines (1-indexed when displayed)."""
    with open(AGENT_FILE, encoding="utf-8") as f:
        return f.read().splitlines()


def find_line(needle: str, start: int = 0) -> int:
    """1-based line number of the first line containing `needle`."""
    for i, line in enumerate(agent_source()[start:], start=start + 1):
        if needle in line:
            return i
    return 0


def show_lines(first: int, last: int, highlight: str = "") -> None:
    """Render agent_sdk_teaching.py lines [first..last] with real line numbers."""
    lines = agent_source()[first - 1 : last]
    body = "\n".join(f"{first + i:>4} | {line}" for i, line in enumerate(lines))
    st.code(body, language="python")
    if highlight:
        st.caption(highlight)


def api_key_state() -> tuple:
    """(ok, message). Checked up front so a dead key is obvious, not a traceback."""
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return False, "ANTHROPIC_API_KEY is not set (looked in week4 .env)."
    return True, f"Key loaded: {key[:14]}... ({len(key)} chars)"


# Line numbers, resolved once from the real file, so the UI can never drift
# from the code. If someone edits agent_sdk_teaching.py, these follow.
L_START = find_line("=== AGENT DEFINITION : START ===")
L_END = find_line("=== AGENT DEFINITION : END ===")
L_TOOL = find_line("@tool(")
L_REGISTER = find_line("tool_registry = create_sdk_mcp_server")
L_TOOLS_END = find_line("ORDER_TOOLS = [")
L_OPTS = find_line("def build_options")
L_RUN = find_line("async def run_agent")
L_IMPORT = find_line("from claude_agent_sdk import")


# ------------------------------------------------------------------ header
st.title("The Agent SDK - the loop you no longer write")
st.caption(
    f"Day 17 live demo . the agent is defined in **agent_sdk_teaching.py**, "
    f"lines **{L_START}-{L_END}**, with **3 tools** . this file just runs it"
)

ok, key_msg = api_key_state()

# --- auth source -----------------------------------------------------------
# The SDK prefers ANTHROPIC_API_KEY when it is set, and falls back to the
# Claude Code CLI login when it is not. Exposing that as a switch means a demo
# still runs when the .env key is out of credit.
with st.sidebar:
    st.markdown("### Auth source")
    use_cli = st.radio(
        "The SDK uses:",
        ["ANTHROPIC_API_KEY (.env)", "Claude Code CLI login"],
        index=0,
        key="auth_source",
        help=(
            "The SDK prefers the env var when set. Unsetting it makes the SDK "
            "fall back to whoever is logged in to the Claude Code CLI."
        ),
    ) == "Claude Code CLI login"
    st.caption(key_msg if ok else "No ANTHROPIC_API_KEY found.")
    if use_cli:
        os.environ.pop("ANTHROPIC_API_KEY", None)
        st.success("Using the CLI login (env var unset for this run).")
    st.divider()
    st.caption(
        "The agent is defined in **agent_sdk_teaching.py**. This file only runs it "
        "and shows it."
    )

if ok and not use_cli:
    st.caption(key_msg)
elif not ok and not use_cli:
    st.error(key_msg)

tab_run, tab_where, tab_loop, tab_knobs, tab_exam = st.tabs([
    "1 . Run the agent",
    "2 . Where the agent is defined",
    "3 . Agent SDK vs Anthropic SDK",
    "4 . Turn the knobs",
    "5 . Exam topics, in this code",
])


# ============================================================ TAB 1 : RUN IT
with tab_run:
    st.subheader("Ask it something. Watch the agent pick its own tools.")

    left, right = st.columns([3, 2])

    with right:
        st.markdown("**Live from the Google Sheet**")
        try:
            orders = agent_sdk_teaching.load_orders()
            st.dataframe(
                [{"order": k, **v} for k, v in orders.items()],
                width="stretch",
                hide_index=True,
            )
            st.caption("Any other ID (e.g. 9999) returns 'order not found'.")
        except Exception as exc:
            st.error(f"Sheet unreachable: {exc}")

    with left:
        question = st.text_input(
            "Customer question",
            value="Who placed order 1001, and how much was it worth?",
        )
        c1, c2 = st.columns(2)
        with c1:
            go = st.button("Run the agent", type="primary", width="stretch")
        with c2:
            mode = st.selectbox(
                "permission_mode", ["dontAsk", "plan", "acceptEdits", "default"], index=0
            )
        st.caption(
            "**One tool:** *where is order 1001?* . "
            "**Two tools:** *who placed 1001 and what was it worth?* . "
            "**All three:** *tell me everything about order 1003* . "
            "**Not found:** *status of order 9999?* . "
            "**Blocked:** *delete all my files*"
        )

    if go:
        # These counters are the point of the demo: WE never incremented a round
        # counter -- we are just watching what the SDK's loop emitted.
        stats = {"messages": 0, "tool_calls": 0, "turns": 0, "tools_used": []}
        # Set if the model call itself was refused (e.g. no credit), so the
        # UI can explain that rather than surface a raw SDK exception.
        api_error = {"hit": False, "detail": ""}
        transcript = st.container()
        raw_messages = []
        started = time.time()

        async def drive():
            async for message in agent_sdk_teaching.run_agent(question, mode):
                yield message

        def render(message):
            """One message off the SDK's stream -> one block on screen."""
            stats["messages"] += 1
            raw_messages.append(f"----- {type(message).__name__} -----\n{message!r}")

            if isinstance(message, SystemMessage) and message.subtype == "init":
                skills = (message.data or {}).get("skills", [])
                loaded = "order-support" in skills
                with transcript:
                    st.success(
                        f"SDK session started . Skill 'order-support' loaded: **{loaded}**"
                        if loaded
                        else "Skill NOT loaded - the rules are missing."
                    )

            elif isinstance(message, (AssistantMessage, UserMessage)):
                for block in (message.content or []) if not isinstance(message.content, str) else []:
                    if isinstance(block, TextBlock) and block.text.strip():
                        low = block.text.lower()
                        if "credit balance" in low or "api error" in low:
                            api_error["hit"] = True
                            api_error["detail"] = block.text.strip()
                            continue
                        # The turn after a Skill call is SKILL.md being read
                        # back. It is already on screen in tab 2, so don't
                        # dump it into the transcript a second time.
                        if "Base directory for this skill" in block.text:
                            with transcript:
                                st.caption(
                                    "SDK read SKILL.md - the rules are in tab 2"
                                )
                            continue
                        with transcript:
                            st.markdown(f"**Claude:** {block.text}")

                    elif isinstance(block, ToolUseBlock):
                        if block.name.startswith("mcp__"):
                            stats["tool_calls"] += 1
                            # Strip the registration prefix -- on screen we want
                            # the name as it was written in agent_sdk_teaching.py.
                            short = block.name.split("__")[-1]
                            stats["tools_used"].append(short)
                            with transcript:
                                st.info(
                                    f"**The agent chose the `{short}` tool**\n\n"
                                    f"`{short}({json.dumps(block.input)})`\n\n"
                                    f"You did not route this. The agent read the "
                                    f"descriptions of all three tools, picked this "
                                    f"one, and the SDK will feed the result back "
                                    f"itself."
                                )
                        else:
                            with transcript:
                                st.caption(f"SDK internal tool: {block.name}")

                    elif isinstance(block, ToolResultBlock):
                        text = block.content
                        if isinstance(text, list):
                            text = " ".join(
                                b.get("text", "") for b in text if isinstance(b, dict)
                            )
                        with transcript:
                            st.caption(f"tool result -> {str(text)[:300]}")

            elif isinstance(message, ResultMessage):
                if str(message.terminal_reason) == "api_error":
                    api_error["hit"] = True
                stats["turns"] = message.num_turns
                usage = message.usage or {}
                tin = (
                    usage.get("input_tokens", 0)
                    + usage.get("cache_read_input_tokens", 0)
                    + usage.get("cache_creation_input_tokens", 0)
                )
                with transcript:
                    st.divider()
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("SDK messages", stats["messages"])
                    m2.metric("Turns the SDK ran", message.num_turns)
                    m3.metric("Your tools called", stats["tool_calls"])
                    m4.metric(
                        "Cost",
                        f"${message.total_cost_usd:.4f}"
                        if message.total_cost_usd
                        else "n/a",
                    )
                    st.caption(
                        f"terminal_reason: `{message.terminal_reason}` . "
                        f"tokens {tin:,} in / {usage.get('output_tokens', 0):,} out . "
                        f"{time.time() - started:.1f}s"
                    )
                    if stats["tools_used"]:
                        used = ", ".join(f"`{t}`" for t in stats["tools_used"])
                        st.caption(
                            f"Tools the agent chose: {used} - out of the three "
                            "it was offered."
                        )
                    st.caption(
                        "**You never wrote a round counter.** The SDK ran "
                        f"{message.num_turns} turns and reported that number itself."
                    )

        async def main():
            async for message in drive():
                render(message)

        billing_note = (
            "**The Anthropic API key has no credit, so the model call was refused.**\n\n"
            "Everything around it worked, and that is still worth showing: the "
            "Skill loaded, the sheet was read, and the SDK ran its loop and "
            "streamed real messages back (open the raw stream below). Only the "
            "model's answer is missing. Top up the key in the Claude Console, "
            "or switch **Auth source** in the sidebar to the Claude Code CLI login "
            "and re-run - either way, no code changes."
        )

        try:
            with st.spinner("The SDK is running its loop..."):
                asyncio.run(main())
            if api_error["hit"]:
                st.error(billing_note)
                if api_error["detail"]:
                    st.caption(f"API said: {api_error['detail']}")
        except Exception as exc:
            msg = str(exc).lower()
            if api_error["hit"] or "credit balance" in msg or "api_error" in msg:
                st.error(billing_note)
            else:
                st.error(f"{type(exc).__name__}: {exc}")

        with st.expander("Raw message stream - exactly what the SDK's loop yielded"):
            st.code("\n\n".join(raw_messages) or "(nothing)", language="text")


# ================================================== TAB 2 : WHERE IT'S DEFINED
with tab_where:
    st.subheader("Point at the screen: this is the agent")
    st.markdown(
        f"The whole agent is `agent_sdk_teaching.py`, lines **{L_START}-{L_END}**. "
        f"That is **{L_END - L_START} lines**, and it is three pieces."
    )

    p1, p2, p3 = st.columns(3)
    p1.metric("1. The tools", f"line {L_TOOL}", "3 Python functions")
    p2.metric("2. Registering", f"line {L_REGISTER}", "hand them to the SDK")
    p3.metric("3. The options", f"line {L_OPTS}", "every knob")

    st.divider()

    piece = st.radio(
        "Show me",
        ["1. The tools", "2. Registering", "3. The options", "Running it", "The Skill"],
        horizontal=True,
        key="code_piece",
    )

    if piece == "1. The tools":
        show_lines(L_TOOL - 6, L_TOOLS_END + 1)
        st.markdown(
            "**Three tools, one job each.** The agent picks between them.\n\n"
            "- The **description** is not a comment - it is the text the agent "
            "reads to decide *which* tool to call. Three clearly-different "
            "descriptions are what make the routing work.\n"
            "- The schema `{\"order_id\": str}` is what the SDK validates against.\n"
            "- Look at what is **missing**: no tool-name check, no dispatch, no "
            "handing the result back. The SDK does all of it."
        )

    elif piece == "2. Registering":
        show_lines(L_REGISTER - 5, L_REGISTER + 11)
        st.markdown(
            "This is how your functions reach the agent. One call, one list.\n\n"
            "- They run **in this process** - nothing is deployed, no port is "
            "opened, no separate program starts.\n"
            "- Registering them is not the same as allowing them. Every tool "
            "still has to appear in `allowed_tools`, which is why "
            "`TOOL_NAMES` is built right here and passed to the options."
        )

    elif piece == "3. The options":
        show_lines(L_OPTS, L_END - 3)
        st.markdown(
            "One object configures the entire agent - model, rules, tools, "
            "permissions, spend cap. Tab 5 walks each field."
        )

    elif piece == "Running it":
        show_lines(L_RUN - 1, L_RUN + 10)
        st.success(
            "This is the entire 'run the agent' story: one `async for`. "
            "Send, check, run the tool, feed the result back, repeat - "
            "all of that is inside `query()`."
        )

    else:
        st.markdown(
            "`system_prompt` is one line on purpose. The real rules live here, "
            "in `.claude/skills/order-support/SKILL.md` - editable without "
            "touching Python:"
        )
        try:
            with open(SKILL_FILE, encoding="utf-8") as f:
                st.code(f.read(), language="markdown")
        except OSError as exc:
            st.error(f"SKILL.md unreadable: {exc}")
        st.caption(
            "It loads only because `cwd` points here AND "
            "`setting_sources=[\"project\"]` allows reading it. Drop either and "
            "it silently never loads - which is why tab 1 prints whether it did."
        )


# ================================================== TAB 3 : WHO RUNS THE LOOP
with tab_loop:
    st.subheader("The same job, both SDKs - run them and compare")
    st.markdown(
        "Same three tools, same sheet, same rules. The **only** difference is "
        "who runs the loop. Run each side and watch what you had to write."
    )

    raw_q = st.text_input(
        "Question for both SDKs",
        value="Who placed order 1001, and how much was it worth?",
        key="compare_q",
    )

    col_raw, col_agent = st.columns(2)

    # ---------------------------------------------------------- raw SDK side
    with col_raw:
        st.markdown("### Anthropic SDK")
        st.caption("`anthropic_sdk.py` - you write the loop")
        run_raw = st.button("Run the Anthropic SDK loop", key="btn_raw", width="stretch")
        raw_box = st.container()

        if run_raw:
            rounds = tools_called = 0
            tok_in = tok_out = 0
            try:
                with st.spinner("Running your hand-written loop..."):
                    for kind, payload in anthropic_sdk.run_anthropic_loop(raw_q):
                        if kind == "round":
                            rounds = payload
                            with raw_box:
                                st.warning(f"**Round {payload}** - a round YOU wrote")
                        elif kind == "usage":
                            tok_in += getattr(payload, "input_tokens", 0)
                            tok_out += getattr(payload, "output_tokens", 0)
                        elif kind == "tool_call":
                            tools_called += 1
                            with raw_box:
                                st.caption(
                                    f"you check stop_reason -> you dispatch "
                                    f"`{payload[0]}({json.dumps(payload[1])})`"
                                )
                        elif kind == "tool_result":
                            with raw_box:
                                st.caption(
                                    f"you feed the result back: "
                                    f"`{json.dumps(payload[1])[:90]}`"
                                )
                        elif kind == "answer":
                            with raw_box:
                                st.markdown(f"**Claude:** {payload}")
                        elif kind == "capped":
                            with raw_box:
                                st.error(f"Hit your {payload}-round cap.")
                        elif kind == "done":
                            with raw_box:
                                st.divider()
                                a, b = st.columns(2)
                                a.metric("Rounds YOU ran", payload["rounds"])
                                b.metric("Tools you dispatched", payload["tool_calls"])
                                st.caption(
                                    f"tokens {tok_in:,} in / {tok_out:,} out . "
                                    "you counted every round above yourself"
                                )
            except Exception as exc:
                low = str(exc).lower()
                with raw_box:
                    if "credit balance" in low:
                        st.error(
                            "**No credit on ANTHROPIC_API_KEY.**\n\n"
                            "The raw SDK can only use the API key - it cannot "
                            "fall back to the Claude Code CLI login the way the "
                            "Agent SDK does. Top up the key to run this side."
                        )
                    else:
                        st.error(f"{type(exc).__name__}: {exc}")

    # -------------------------------------------------------- agent SDK side
    with col_agent:
        st.markdown("### Agent SDK")
        st.caption("`agent_sdk_teaching.py` - the SDK runs the loop")
        run_ag = st.button("Run the agent", key="btn_agent", width="stretch")
        ag_box = st.container()

        if run_ag:
            ag = {"msgs": 0, "tools": 0}

            async def compare_run():
                async for m in agent_sdk_teaching.run_agent(raw_q):
                    ag["msgs"] += 1
                    if isinstance(m, (AssistantMessage, UserMessage)) and not isinstance(
                        m.content, str
                    ):
                        for blk in m.content or []:
                            if isinstance(blk, ToolUseBlock) and blk.name.startswith("mcp__"):
                                ag["tools"] += 1
                                short = blk.name.split("__")[-1]
                                with ag_box:
                                    st.caption(
                                        f"the SDK chose and ran "
                                        f"`{short}({json.dumps(blk.input)})`"
                                    )
                            elif isinstance(blk, TextBlock) and blk.text.strip():
                                if "Base directory for this skill" in blk.text:
                                    continue
                                with ag_box:
                                    st.markdown(f"**Claude:** {blk.text}")
                    elif isinstance(m, ResultMessage):
                        with ag_box:
                            st.divider()
                            a, b = st.columns(2)
                            a.metric("Turns the SDK ran", m.num_turns)
                            b.metric("Tools it chose", ag["tools"])
                            st.caption(
                                f"terminal_reason: `{m.terminal_reason}` . "
                                f"{ag['msgs']} messages streamed back"
                            )
                            st.caption(
                                "You wrote none of that. No round counter, no "
                                "stop_reason check, no dispatch."
                            )

            try:
                with st.spinner("The SDK is running its loop..."):
                    asyncio.run(compare_run())
            except Exception as exc:
                low = str(exc).lower()
                with ag_box:
                    if "credit balance" in low or "api_error" in low:
                        st.error(
                            "No credit on the API key - switch **Auth source** "
                            "in the sidebar to the Claude Code CLI login."
                        )
                    else:
                        st.error(f"{type(exc).__name__}: {exc}")

    st.divider()

    # ------------------------------------------------ the code, side by side
    st.markdown("#### The code that produced those two runs")
    c_raw, c_agent = st.columns(2)
    with c_raw:
        st.markdown("**Anthropic SDK** - the loop is yours")
        st.code(
            'for round_num in range(1, MAX_ROUNDS + 1):\n'
            '    response = client.messages.create(...)\n'
            '    messages.append({"role": "assistant", ...})\n'
            '\n'
            '    if response.stop_reason == "tool_use":\n'
            '        for block in response.content:\n'
            '            fn = DISPATCH[block.name]      # you dispatch\n'
            '            result = fn(**block.input)\n'
            '            results.append({"type": "tool_result", ...})\n'
            '        messages.append({"role": "user", "content": results})\n'
            '    elif response.stop_reason == "end_turn":\n'
            '        return final_text',
            language="python",
        )
        st.error("You count rounds. You read stop_reason. You dispatch. You append.")
    with c_agent:
        st.markdown("**Agent SDK** - the loop is the SDK's")
        show_lines(L_RUN + 6, L_RUN + 8)
        st.success("You read messages. That is the entire loop.")

    st.divider()
    st.markdown("#### Proof, not claim")
    st.markdown("Search `agent_sdk_teaching.py` for the machinery you just saw on the left:")

    src = "\n".join(agent_source())
    checks = [
        ("for round", r"for\s+round"),
        ("stop_reason check", r"stop_reason\s*=="),
        ("tool-name dispatch", r"DISPATCH\["),
        ("messages.append", r"messages\.append"),
    ]
    cols = st.columns(len(checks))
    for col, (label, pattern) in zip(cols, checks):
        hits = len(re.findall(pattern, src))
        col.metric(label, f"{hits} found", "absent" if hits == 0 else "present")
    st.caption(
        "All four are in anthropic_sdk.py on the left. None are in agent_sdk_teaching.py - "
        "the SDK owns them now."
    )

    st.divider()
    with st.expander("The full comparison table"):
        st.markdown(
            "| | Anthropic SDK | Agent SDK |\n"
            "|---|---|---|\n"
            "| **Execution** | stateless request / response | runs the agent loop for you |\n"
            "| **Tools** | you parse tool calls and run them | executes tools autonomously |\n"
            "| **Tool schema** | hand-written JSON per tool | generated from `@tool` |\n"
            "| **Context** | you append every turn by hand | managed for you |\n"
            "| **Rules** | all crammed into one system prompt | a Skill file, edited without code |\n"
            "| **System access** | none - you build the sandbox | built-in, and gated by permissions |\n"
            "| **Safety** | you write your own checks | permission modes, allow/deny lists, hooks |\n"
            "| **Cap** | your own `range()` | `max_turns` |\n"
            "| **Auth** | API key only | API key or the Claude Code CLI login |\n"
            "| **Best for** | one-shot calls, extraction | multi-step autonomous work |"
        )



# ====================================================== TAB 4 : TURN THE KNOBS
with tab_knobs:
    st.subheader("Change a setting, see what the agent becomes")
    st.markdown(
        "`ClaudeAgentOptions` is the control panel. Move these and the object "
        "below changes - this is the real thing `build_options()` returns."
    )

    k1, k2 = st.columns(2)
    with k1:
        d_mode = st.selectbox(
            "permission_mode",
            ["dontAsk", "default", "acceptEdits", "plan", "auto", "bypassPermissions"],
        )
        d_turns = st.slider("max_turns", 1, 20, agent_sdk_teaching.MAX_TURNS)
    with k2:
        d_tools = st.multiselect(
            "allowed_tools",
            agent_sdk_teaching.TOOL_NAMES + ["Read", "Bash", "WebSearch"],
            default=list(agent_sdk_teaching.TOOL_NAMES),
        )
        d_block = st.multiselect(
            "disallowed_tools",
            ["Bash", "Write", "Edit", "WebSearch", "WebFetch"],
            default=["Bash", "Write", "Edit", "WebSearch", "WebFetch"],
        )

    st.caption(
        "`mcp_servers` is just the SDK's name for the registry your three "
        "tools live in - the same `tool_registry` from tab 2. Nothing external "
        "is involved; they run in this process."
    )
    st.code(
        f"""ClaudeAgentOptions(
    model={agent_sdk_teaching.MODEL!r},
    fallback_model={agent_sdk_teaching.MODEL!r},
    system_prompt={agent_sdk_teaching.SYSTEM_PROMPT!r},
    mcp_servers={{"orders": tool_registry}},
    cwd=HERE,
    setting_sources=["project"],
    skills=["order-support"],
    allowed_tools={d_tools!r},
    disallowed_tools={d_block!r},
    permission_mode={d_mode!r},
    max_turns={d_turns},
)""",
        language="python",
    )

    # The warnings are the teaching moment -- each one is a real footgun.
    if d_mode == "bypassPermissions":
        st.error(
            "**bypassPermissions**: tools run with no checks, and it needs "
            "`allow_dangerously_skip_permissions=True`. Note the footgun - "
            "`allowed_tools` does **not** constrain it, so unlisted tools fall "
            "through and get approved. Only `disallowed_tools` still blocks. "
            "Never use this outside a sandbox."
        )
    elif d_mode == "default":
        st.warning(
            "**default**: nothing is auto-approved; unmatched tools go to your "
            "`canUseTool` callback. In an unattended run there is nobody to "
            "answer - it will hang. That is why this demo ships `dontAsk`."
        )
    elif d_mode == "dontAsk":
        st.success(
            "**dontAsk**: fail-closed. Anything not in `allowed_tools` is denied "
            "outright rather than prompted. This is the right default for an "
            "agent nobody is watching."
        )
    elif d_mode == "plan":
        st.info(
            "**plan**: the agent explores and strategises only - it maps out "
            "changes without editing or executing."
        )
    elif d_mode == "acceptEdits":
        st.warning(
            "**acceptEdits**: auto-approves local file edits and filesystem "
            "operations, including mkdir, rm and mv."
        )
    else:
        st.info(
            "**auto**: a model classifier approves or denies, easing approval "
            "fatigue while still gating risky calls."
        )

    if "Bash" in d_tools and "Bash" in d_block:
        st.error(
            "Bash is in **both** lists - and it stays blocked. Deny rules are "
            "checked before allow rules, so `disallowed_tools` always wins. "
            "That ordering is the pipeline in the next tab."
        )


# ==================================================== TAB 5 : EXAM TOPICS
with tab_exam:
    st.subheader("Where each exam topic is enforced in this code")
    st.caption(
        "Domain 1 . Agentic Architecture & Orchestration (~27%). "
        "Every row points at a real line in agent_sdk_teaching.py."
    )

    rows = [
        (
            "The rename trap",
            f"line {L_IMPORT}",
            "`from claude_agent_sdk import ...`. The old `claude_code_sdk` / "
            "`ClaudeCodeOptions` names are deprecated and will not import.",
        ),
        (
            "Who runs the loop",
            f"line {L_RUN}",
            "One `async for` over `query()`. No round counter, no `stop_reason` "
            "check, no dispatch - tab 3 proves all four are absent.",
        ),
        (
            "query() vs ClaudeSDKClient",
            f"line {L_RUN}",
            "`query()` is one-shot and stateless per call - right for this demo. "
            "`ClaudeSDKClient` holds a session open across turns for an ongoing "
            "conversation. Same `ClaudeAgentOptions` either way.",
        ),
        (
            "Your own tools: the 3 steps",
            f"lines {L_TOOL}, {L_REGISTER}, {L_OPTS}",
            "Decorate each function with `@tool` -> register the list -> add "
            "every name to `allowed_tools`. Miss that last step and the agent "
            "cannot call the tool even though it exists.",
        ),
        (
            "model + fallback_model",
            f"line {find_line('model=MODEL')}",
            "Both pinned to the same string, so nothing silently runs on a "
            "bigger, pricier model.",
        ),
        (
            "system_prompt vs Skill",
            f"line {find_line('system_prompt=SYSTEM_PROMPT')}",
            "One line in Python; the real rules live in SKILL.md. Loading it "
            "needs `cwd` **and** `setting_sources=['project']` - drop either "
            "and it silently never loads.",
        ),
        (
            "allowed_tools (the allow-list)",
            f"line {find_line('allowed_tools=')}",
            "Read, Write, Bash and WebSearch are ON by default. Not listing "
            "them is what turns them off.",
        ),
        (
            "disallowed_tools (hard block)",
            f"line {find_line('disallowed_tools=')}",
            "Hard blocks - they win over everything, including "
            "bypassPermissions. The only reliable way to guarantee a tool "
            "never runs.",
        ),
        (
            "permission_mode",
            f"line {find_line('permission_mode=permission_mode')}",
            "`dontAsk` = fail-closed: deny rather than prompt. Correct for an "
            "unattended agent. Never `bypassPermissions` outside a sandbox.",
        ),
        (
            "max_turns (the spend cap)",
            f"line {find_line('max_turns=MAX_TURNS')}",
            f"Capped at {agent_sdk_teaching.MAX_TURNS}. A model that never says it is "
            "done cannot run up an unbounded bill.",
        ),
    ]

    for topic, where, detail in rows:
        with st.expander(f"**{topic}**  .  {where}"):
            st.markdown(detail)

    st.divider()
    st.markdown("#### The permission pipeline - the order that explains the bugs")
    st.markdown(
        "When the model asks for a tool, the SDK decides in this fixed order. "
        "Knowing it prevents the classic *why wasn't that blocked?*:"
    )
    pipeline = [
        ("Hooks", "a `PreToolUse` hook can deny outright - hooks run first"),
        ("Deny rules", "`disallowed_tools` blocks it, even under bypass"),
        ("Permission mode", "bypass / acceptEdits approve; others fall through"),
        ("Allow rules", "`allowed_tools` approves listed tools"),
        ("Your callback", "`canUseTool` decides anything left"),
    ]
    for i, (step, note) in enumerate(pipeline, start=1):
        st.markdown(f"{i}. **{step}** - {note}")
    st.warning(
        "**The footgun:** `allowed_tools` does *not* constrain "
        "`bypassPermissions` - unlisted tools fall through and get approved. "
        "For a hard block you need `disallowed_tools`, which is why this agent "
        "sets both."
    )

    st.divider()
    st.markdown("#### Two things this demo does not use - and why")
    n1, n2 = st.columns(2)
    n1.info(
        "**Hooks** (`PreToolUse` / `PostToolUse`) - your code, run at key "
        "moments. A programmable layer *on top of* permissions, not a "
        "replacement. This agent's allow/deny lists are strict enough that it "
        "needs none."
    )
    n2.info(
        "**Subagents** - delegate a focused slice of work. The inheritance "
        "trap: they inherit `bypassPermissions`, `acceptEdits` and `auto` from "
        "the parent and cannot override them per subagent. A loosely-"
        "permissioned parent silently widens your blast radius."
    )
