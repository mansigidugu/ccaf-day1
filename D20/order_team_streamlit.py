"""
order_team_streamlit.py -- HUMAN-IN-THE-LOOP & ESCALATION, as a live and
inspectable control room.

    Day 20 of the Claude Agent SDK series. The story of an AI support desk
    that learns the most important skill an agent can have: knowing which
    decisions are not its to make.

    THE SAME AGENT AS order_team_teaching.py. NOTHING ON SCREEN IS SIMULATED.
    Every number is read off the Agent SDK's own message stream.

WHAT THIS WINDOW IS FOR
  order_team_teaching.py prints an answer. This shows the machinery that produced it:

      WHO      the router and its three specialists, built from the live
               AgentDefinition objects -- not typed out by hand
      WHAT     every tool call, in order, with its arguments, its result and
               how long it took
      WHERE    the spreadsheet: the tabs, the columns, and the rows the
               specialists actually read back
      HOW MUCH tokens and cost per conversation, as the SDK reports them
      WHY      who owned the decision -- Handle By AI or Human -- and the
               webhook that hands the case over
      OFFERED  the MCP server's whole catalogue, asked for by hand over the
               same stdio transport the agent uses -- because the gap between
               what was OFFERED and what got USED is the lesson
  Ten tabs, one run. Run it once and read down them in order.

READ THESE TWO TILES FIRST
      DELEGATIONS   0, 1, 2 or 3 -- the router decides at runtime
      ACTION BY     Handle By AI, or Human -- who owns the outcome

  The agent never pauses and never waits for a keypress. It records who owns
  the decision and moves on; a person works the queue afterwards.

RUN IT
      uv add streamlit
      uv run streamlit run order_team_streamlit.py

  Setup, the sheet layout and the rulebook are in cmd.txt.

--------------------------------------------------------------------------
  Day 20  --  Human-in-the-Loop & Escalation
              (Agent SDK + MCP + subagents + Skills)
  Built for the Claude Agent SDK series by GrowwStacks <hello@growwstacks.com>
  Companion to: order_team_teaching.py (the CLI walkthrough)
  Model: claude-haiku-4-5-20251001    Version 1.0    2026-09-01
--------------------------------------------------------------------------
"""

import asyncio
import json
import os
import queue
import re
import subprocess
import threading
import time
import urllib.request
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from html import escape

import streamlit as st
from dotenv import load_dotenv

from claude_agent_sdk import AgentDefinition, ClaudeAgentOptions, query
from claude_agent_sdk.types import (
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

load_dotenv()

# The day's topic, split so the masthead can set the second half in the
# accent colour. APP_TITLE stays a single plain string because the browser
# tab, the sidebar and the footer all want it that way.
APP_TITLE = "Human-in-the-Loop & Escalation"
APP_TITLE_LEAD = "Human-in-the-Loop"
APP_TITLE_TAIL = "& Escalation."
APP_KICKER = "Day 20  ·  Claude Agent SDK series"
APP_STORY = (
    "The story of an AI support desk that learns the most important skill an "
    "agent can have: knowing which decisions are not its to make. It still "
    "answers every customer. What changes is one column on the ticket -- "
    "Handle By AI, or Human."
)
APP_VERSION = "1.0"
APP_AUTHOR = "GrowwStacks"
APP_CONTACT = "hello@growwstacks.com"
APP_BUILT = "2026-09-01"

# ==========================================================================
# 1. CONFIGURATION -- identical to order_team_teaching.py. One agent, three front ends.
# ==========================================================================

MODEL = "claude-haiku-4-5-20251001"
MAX_TURNS = 30
MAX_OUTPUT_TOKENS = 2024

# The CLI renamed the delegation tool from "Task" to "Agent" and answers to
# both. Get the name wrong and a delegation silently does not count as one.
DELEGATE_TOOLS = ("Agent", "Task")

# The two dropdown values in the Tickets tab, spelled here exactly as the
# sheet spells them, because ACTION BY is matched against these strings.
ACTED_BY_AI = "Handle By AI"
ACTED_BY_HUMAN = "Human"

# The sheets tools that actually put VALUES in cells. add_rows is deliberately
# NOT here: it takes a row COUNT, not data, so it inserts a blank row and
# records nothing.
WRITE_TOOLS = ("update_cells", "batch_update_cells")

# This folder's four Skills, one per agent. Used to filter the startup lines:
# the session also carries every global and plugin skill on the machine.
OUR_SKILLS = ("support-router", "order-lookup", "delay-analysis", "ticket-writer")

# Where an escalation goes once it stops being the agent's problem. Read from
# the environment: the UUID in the path IS the credential, so it lives in .env
# alongside the API keys, never in this file.
WEBHOOK_URL = os.getenv("ESCALATION_WEBHOOK_URL", "").strip()

# The Slack side of the same handoff. The webhook above feeds a workflow; this
# puts the case in front of the people who work the queue, in their channel.
# Both fire on the same condition and neither replaces the other.
#
# THE TOKEN IS THE CREDENTIAL, which is why it is read from the environment
# and never written in a .py -- an xoxb- token posts as your bot until it is
# revoked. The channel id is not a secret, but it is CONFIGURATION: which team
# gets woken up is a deployment decision, not a code one.
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "").strip()
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID", "").strip()
SLACK_TEAM_ID = os.getenv("SLACK_TEAM_ID", "").strip()   # optional, for links
SLACK_API_URL = "https://slack.com/api/chat.postMessage"

# The rule is "within N days of TODAY", and a model has no clock. Stamp it in.
TODAY = date.today().isoformat()

SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
SERVICE_ACCOUNT_PATH = os.getenv("SERVICE_ACCOUNT_PATH")
HERE = os.path.dirname(os.path.abspath(__file__))
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}" if SHEET_ID else ""

# Policy is DATA, not code. The same file order_team_teaching.py reads -- one copy, and
# no refund number anywhere in this app or in any SKILL.md.
RULEBOOK_PATH = os.path.join(HERE, "refund_rulebook.txt")
try:
    with open(RULEBOOK_PATH, encoding="utf-8") as fh:
        RULEBOOK = fh.read().strip()
    RULEBOOK_ERROR = ""
except OSError as exc:
    # A missing rulebook does not produce a broken run you would notice -- it
    # produces a confident agent inventing refund percentages. The CLI raises
    # SystemExit here; a UI has to stay up to SAY so, and it blocks Run below.
    RULEBOOK, RULEBOOK_ERROR = "", str(exc)

def rulebook_sections(text: str):
    """Split the rulebook into its underlined headings -> (preamble, sections).

    Deliberately does not know how many rules there are, or what they are
    called. The whole point of policy living in a .txt is that it is edited
    without touching this app, so anything here that counted the rules would
    be wrong the first time somebody added one. A heading is simply any line
    with a row of dashes under it.
    """
    lines = text.splitlines()
    preamble, sections, title, body = [], [], "", []
    for i, line in enumerate(lines):
        stripped = line.strip()
        under = lines[i + 1].strip() if i + 1 < len(lines) else ""
        if stripped and under and set(under) == {"-"}:
            if title:
                sections.append((title, "\n".join(body).strip()))
            title, body = stripped, []
            continue
        if stripped and set(stripped) in ({"-"}, {"="}):
            continue                      # the underline itself
        (body if title else preamble).append(line)
    if title:
        sections.append((title, "\n".join(body).strip()))
    return "\n".join(preamble).strip(), sections


WHERE_THE_DATA_IS = (
    f"The order data lives in Google spreadsheet ID {SHEET_ID}. Always use that "
    "spreadsheet -- never ask which sheet to read and never ask for a "
    "spreadsheet ID."
)

# Role + a fact the model cannot look up + the policy, pasted in verbatim.
# SKILL.md says HOW TO BEHAVE; the rulebook says WHAT THE POLICY IS.
ROUTER_PROMPT = (
    "You are a concise order-support agent coordinating three specialists. "
    "You cannot read or write the spreadsheet yourself -- delegate with the "
    f"Agent tool. Today's date is {TODAY}. Use it, and only it, when working "
    "out how old an order is -- never guess today's date."
    f"\n\nThe refund policy below is the ONLY refund policy. Follow it exactly "
    f"and never reason past it:\n\n{RULEBOOK}"
)

# ---------- The three specialists ----------
# `description` is what the ROUTER reads when it picks who to hand the job to,
# so it is written for that reader -- not as documentation.
#
# No tools=[...] list: naming two tools would mean WE chose the tool and the
# model only filled in the arguments. Each specialist sees the server's whole
# catalogue and picks. disallowedTools drops the delegation tool, so none of
# them can delegate onward, and drops the write tools from the two readers.
SUBAGENTS = {
    "order-lookup": AgentDefinition(
        description=(
            "Looks up ONE order in the Order tab and reports its status, carrier, "
            "ETA, category and order date. Use this first for any order question, "
            "including refund questions. Returns 'not_found' if the order ID is "
            "not in the sheet."
        ),
        prompt=(
            "You are an order-lookup specialist reporting to another agent. "
            f"{WHERE_THE_DATA_IS} Read the 'Order' tab only."
        ),
        skills=["order-lookup"],
        mcpServers=["sheets"],
        disallowedTools=[*DELEGATE_TOOLS,
                         "mcp__sheets__update_cells",
                         "mcp__sheets__batch_update_cells"],
        model=MODEL,
    ),
    "delay-analyst": AgentDefinition(
        description=(
            "Reads the Delays tab and reports WHY one order is late. Use only "
            "after order-lookup reports a delayed status. Returns "
            "'no_reason_logged' if no reason has been written down yet."
        ),
        prompt=(
            "You are a delay-analysis specialist reporting to another agent. "
            f"{WHERE_THE_DATA_IS} Read the 'Delays' tab only."
        ),
        skills=["delay-analysis"],
        mcpServers=["sheets"],
        disallowedTools=[*DELEGATE_TOOLS,
                         "mcp__sheets__update_cells",
                         "mcp__sheets__batch_update_cells"],
        model=MODEL,
    ),
    # The only agent that WRITES. Everyone else reads.
    "ticket-writer": AgentDefinition(
        description=(
            "Appends one row to the Tickets tab recording what happened and who "
            "decided it. Use LAST, once per customer case, after the answer is "
            "known. Returns the ticket ID it wrote."
        ),
        prompt=(
            "You are a ticketing specialist reporting to another agent. "
            f"{WHERE_THE_DATA_IS} Write to the 'Tickets' tab only. Never edit "
            "the 'Order' or 'Delays' tabs."
        ),
        skills=["ticket-writer"],
        mcpServers=["sheets"],
        disallowedTools=list(DELEGATE_TOOLS),
        model=MODEL,
    ),
}

# ONE GLOBAL approval list, not a per-agent tool set. Worth staring at now
# that a WRITE tool is on it: "mcp__sheets__*" approves add_rows for EVERY
# agent, including the two that must never write. Only their Skills and their
# disallowedTools stop them. That is the day's lesson, sitting in the config.
ALLOWED_TOOLS = [
    *DELEGATE_TOOLS,
    "mcp__sheets__*",
    "Skill(order-lookup)",
    "Skill(delay-analysis)",
    "Skill(ticket-writer)",
]

MCP_SERVERS = {
    "sheets": {
        "command": "uvx",
        "args": ["--with", "mcp<2", "mcp-google-sheets@latest"],
        # Credentials go to the SERVER. No agent ever sees the key.
        "env": {"SERVICE_ACCOUNT_PATH": SERVICE_ACCOUNT_PATH},
        "alwaysLoad": True,
    }
}


def build_options(resume=None, max_turns=MAX_TURNS,
                  max_output=MAX_OUTPUT_TOKENS, model=MODEL) -> ClaudeAgentOptions:
    """Built per Send, because the SECOND message onwards must resume the
    FIRST message's session. Without resume every Send is a brand new
    conversation: the agent forgets which order you meant and -- the reason it
    matters here -- forgets it already filed a ticket, so it files another.
    One chat = one session = one ticket, until Clear."""
    return ClaudeAgentOptions(
        resume=resume,
        model=model,
        fallback_model=model,
        system_prompt=ROUTER_PROMPT,
        agents=SUBAGENTS,
        mcp_servers=MCP_SERVERS,
        cwd=HERE,
        setting_sources=["project"],
        # Only the router's own Skill. The specialists declare theirs above.
        skills=["support-router"],
        env={
            "CLAUDE_CODE_MAX_OUTPUT_TOKENS": str(max_output),
            # WAIT for the sheets server, or the specialists start while it is
            # still connecting, every tool lookup answers "servers still
            # connecting", and they burn their turns retrying.
            "MCP_CONNECTION_NONBLOCKING": "0",
        },
        allowed_tools=ALLOWED_TOOLS,
        permission_mode="dontAsk",
        max_turns=max_turns,
    )


# Labelled against the sheet as it actually stands, not against the tidy
# demo data the notes describe. Read the caption under the picker before you
# call one of these outcomes a bug.
PRESETS = [
    ("1001 -- Electronics, dated 62 days back: window closed, expect Human",
     "I want to return order 1001, can I get a refund?"),
    ("1004 -- Perishable AND 30 days back: window closes first, expect Human",
     "I want a refund on order 1004 please."),
    ("1002 -- Apparel, 34 days back: window closed, expect Human",
     "I want a refund on order 1002, it was late and I am done waiting."),
    ("3001 -- damaged: no rule covers damage at all, expect Human",
     "Order 3001 arrived damaged. Can I get a refund?"),
    ("no ID -- ticket says not_given, and the ONLY Handle By AI in this sheet",
     "I want a refund on something I ordered last week."),
]

# The sheet, as the Skills describe it. Change a column here and you must
# change it in .claude/skills/*/SKILL.md too -- nothing in Python checks it.
SHEET_SCHEMA = {
    "Order": {
        "access": "READ",
        "owner": "order-lookup",
        "columns": ["Order ID", "Status", "Carrier", "ETA Days", "Category",
                    "Delivery Date", "Customer Email", "Customer Name",
                    "Order Value"],
        "note": "Status, Category and the date column all decide the refund -- "
                "one rule each, and all three must pass. Email + Name are "
                "for the escalation handoff. Email is column G and Name is H -- "
                "swap the columns and you must swap order-lookup/SKILL.md. "
                "NOTE: the live sheet heads column F 'Delivery Date', while the "
                "Skill and the rulebook both say 'Date'. The positions line up "
                "so it runs, but the refund window is being measured off the "
                "DELIVERY date. If it should be the ORDER date, that is a sheet "
                "change, not a code change. Column I 'Order Value' is in the "
                "sheet and in no Skill, so no agent reads it.",
    },
    "Delays": {
        "access": "READ",
        "owner": "delay-analyst",
        "columns": ["Order ID", "Reason"],
        "note": "An order can be marked delayed in Order before anyone has "
                "written down why. The specialist reports no_reason_logged "
                "rather than inventing a plausible reason.",
    },
    "Tickets": {
        "access": "WRITE",
        "owner": "ticket-writer",
        "columns": ["Ticket ID", "Order ID", "Issue", "Resolution", "Action By"],
        "note": "Action By is a DROPDOWN: 'Handle By AI' or 'Human', spelled "
                "exactly. Any other spelling lands as a cell that will not "
                "filter. Every case gets exactly one row -- including the dull "
                "ones, or 'the agent handled it' is a claim nobody can check.",
    },
}


# ==========================================================================
# 2. THEME -- ONE palette. This page is light, always.
#    No picker, no `prefers-color-scheme`, and nothing read off the browser:
#    a control room that changes colour depending on whose laptop is open is
#    a control room whose screenshots cannot be compared. The tokens below are
#    the validated data-viz reference palette, and they are the only ones.
#
#    Streamlit's OWN chrome -- widgets, sidebar, code blocks -- follows the
#    viewer's system theme unless it is told not to. That is pinned in
#    .streamlit/config.toml (base = "light"), NOT here, because it is read
#    before this file runs. Delete that file and the OS gets a vote again.
# ==========================================================================

PALETTE = {

        "PLANE": "#f9f9f7", "SURFACE": "#fcfcfb", "SUNK": "#f2f1ed",
        "INK": "#0b0b0b", "INK2": "#52514e", "MUTED": "#898781",
        "LINE": "#e1e0d9", "RULE": "#c3c2b7",
        "BLUE": "#2a78d6", "ORANGE": "#eb6834", "AQUA": "#1baf7a",
        "VIOLET": "#4a3aa7", "TRACK": "#cde2fb",
        # Darker steps of the same hues, for TEXT. The mark colours above sit
        # below 4.5:1 on this surface, so a chip or a tile value wears these
        # instead and the dot/border keeps the hue.
        "BLUEINK": "#256abf", "AQUAINK": "#0f7a55", "ORANGEINK": "#c2521f",
        "VIOLETINK": "#4a3aa7", "SERIOUSINK": "#c2521f", "CRITINK": "#d03b3b",
        "GOOD": "#0ca30c", "WARN": "#fab219", "SERIOUS": "#ec835a",
        "CRIT": "#d03b3b", "GOODINK": "#006300",
        "SHADOW": "0 1px 2px rgba(11,11,11,.06)",
        "CODEBG": "#f2f1ed",
}


CSS = """
<style>
/* ---- the app plane ------------------------------------------------ */
.stApp, [data-testid="stAppViewContainer"] { background: __PLANE__; }
[data-testid="stSidebar"] { background: __SURFACE__; border-right:1px solid __LINE__; }
.stApp, .stApp p, .stApp li, .stApp label, .stApp span { color: __INK__; }
.block-container { padding-top:1.1rem; padding-bottom:3rem; max-width:1500px; }

/* ---- masthead ------------------------------------------------------ */
.gs-mast { position:relative; background:__SURFACE__;
  /* faint graph paper, drawn from the palette's own hairline token rather
     than a second hardcoded grey, so the grid moves with the palette */
  background-image:linear-gradient(__LINE__ 1px, transparent 1px),
                   linear-gradient(90deg, __LINE__ 1px, transparent 1px);
  background-size:100% 34px, 34px 100%;
  border:1px solid __LINE__; border-left:4px solid __ORANGE__;
  border-radius:12px; padding:1.5rem 1.7rem 1.15rem; margin-bottom:1.1rem;
  box-shadow:__SHADOW__; }
.gs-mast .kicker { display:block; font-size:.64rem; letter-spacing:.16em;
  text-transform:uppercase; color:__MUTED__; font-weight:600; }
.gs-mast .rule { display:block; width:62px; height:5px; background:__ORANGE__;
  border-radius:2px; margin:.75rem 0 .85rem; }
.gs-mast h1 { font-family:"Iowan Old Style","Palatino Linotype",Palatino,
  Georgia,"Times New Roman",serif;
  font-size:2.6rem; font-weight:700; line-height:1.06; margin:0;
  color:__INK__; letter-spacing:-.02em; }
/* the second half carries the accent -- em is the hook, not italics */
.gs-mast h1 em { display:block; font-style:normal; color:__ORANGEINK__; }
.gs-mast .sub { display:block; margin-top:.85rem; max-width:68ch;
  font-size:.88rem; line-height:1.62; color:__INK2__; }
.gs-mast .sig { display:block; margin-top:1.05rem; padding-top:.7rem;
  border-top:1px solid __LINE__; font-size:.71rem; color:__MUTED__;
  line-height:1.6; }

/* ---- KPI tiles: auto-fit grid, so it reflows instead of scrolling --- */
.gs-grid { display:grid; gap:.6rem; margin:.35rem 0 .9rem;
  grid-template-columns:repeat(auto-fit, minmax(148px, 1fr)); }
.gs-tile { background:__SURFACE__; border:1px solid __LINE__; border-radius:10px;
  padding:.6rem .7rem .65rem; box-shadow:__SHADOW__; min-width:0; }
.gs-tile .lab { font-size:.63rem; letter-spacing:.09em; text-transform:uppercase;
  color:__MUTED__; font-weight:600; display:block; margin-bottom:.2rem; }
.gs-tile .val { font-size:1.42rem; font-weight:640; line-height:1.15;
  color:__INK__; overflow-wrap:anywhere; }
.gs-tile .val.sm { font-size:1.02rem; }
.gs-tile .hint { font-size:.66rem; color:__INK2__; margin-top:.22rem;
  line-height:1.35; display:block; }
.t-blue .val{color:__BLUEINK__}    .t-violet .val{color:__VIOLETINK__}
.t-aqua .val{color:__AQUAINK__}    .t-orange .val{color:__ORANGEINK__}
.t-good .val{color:__GOODINK__}    .t-warn .val{color:__SERIOUSINK__}
.t-crit .val{color:__CRITINK__}    .t-mute .val{color:__INK2__}

/* ---- hero: the one number the view leads with ---------------------- */
.gs-hero { background:__SURFACE__; border:1px solid __LINE__; border-radius:12px;
  padding:1rem 1.1rem; box-shadow:__SHADOW__; }
.gs-hero .lab { font-size:.63rem; letter-spacing:.09em; text-transform:uppercase;
  color:__MUTED__; font-weight:600; }
.gs-hero .fig { font-size:2.9rem; font-weight:640; line-height:1.05;
  color:__INK__; margin:.15rem 0 .1rem; }
.gs-hero .fig.ai { color:__GOODINK__; } .gs-hero .fig.human { color:__SERIOUSINK__; }
.gs-hero .fig.bad { color:__CRITINK__; }
.gs-hero .note { font-size:.78rem; color:__INK2__; line-height:1.5; }

/* ---- chips --------------------------------------------------------- */
.chip { display:inline-block; font-size:.66rem; font-weight:600;
  padding:.1rem .42rem; border-radius:5px; border:1px solid __LINE__;
  color:__INK2__; background:__SUNK__; white-space:nowrap; }
.chip.router{ border-color:__VIOLET__; color:__VIOLETINK__;  background:transparent; }
.chip.spec  { border-color:__BLUE__;   color:__BLUEINK__;    background:transparent; }
.chip.write { border-color:__CRIT__;   color:__CRITINK__;    background:transparent; }
.chip.read  { border-color:__AQUA__;   color:__AQUAINK__;    background:transparent; }
.chip.sdk   { border-color:__RULE__;   color:__INK2__;       background:transparent; }
.chip.ok    { border-color:__GOOD__;   color:__GOODINK__;    background:transparent; }
.chip.bad   { border-color:__CRIT__;   color:__CRITINK__;    background:transparent; }

/* ---- the step stream ----------------------------------------------- */
.gs-stream { background:__SURFACE__; border:1px solid __LINE__; border-radius:10px;
  padding:.5rem .2rem .5rem 0; max-height:640px; overflow:auto; }
.step { display:grid; grid-template-columns:14px 1fr; gap:.5rem;
  padding:.28rem .8rem .28rem .6rem; }
.step .rail { position:relative; }
.step .rail::before { content:""; position:absolute; left:5px; top:0; bottom:-.6rem;
  width:1px; background:__LINE__; }
.step .dot { position:absolute; left:1px; top:.42rem; width:9px; height:9px;
  border-radius:50%; background:__MUTED__; border:2px solid __SURFACE__;
  box-shadow:0 0 0 1px __RULE__; }
.step.deleg .dot{background:__VIOLET__} .step.read .dot{background:__AQUA__}
.step.write .dot{background:__CRIT__}   .step.text .dot{background:__BLUE__}
.step.sys .dot{background:__RULE__}     .step.err .dot{background:__CRIT__}
.step.done .dot{background:__GOODINK__}
.step .head { display:flex; flex-wrap:wrap; gap:.35rem; align-items:baseline; }
.step .title { font-size:.8rem; font-weight:600; color:__INK__;
  overflow-wrap:anywhere; }
.step .at { font-size:.66rem; color:__INK2__; margin-left:auto;
  font-variant-numeric:tabular-nums; }
.step .body { font-size:.76rem; color:__INK2__; line-height:1.5;
  margin-top:.12rem; overflow-wrap:anywhere; }
.step .mono { font-family:ui-monospace,"Cascadia Code",Consolas,monospace;
  font-size:.71rem; background:__CODEBG__; border:1px solid __LINE__;
  border-radius:6px; padding:.3rem .45rem; display:block; margin-top:.25rem;
  white-space:pre-wrap; overflow-wrap:anywhere; color:__INK2__; }
.step .said { border-left:2px solid __BLUE__; padding-left:.55rem; color:__INK__; }

/* ---- panels, tables, bars ------------------------------------------ */
.gs-card { background:__SURFACE__; border:1px solid __LINE__; border-radius:10px;
  padding:.8rem .9rem; box-shadow:__SHADOW__; margin-bottom:.7rem; }
.gs-card h4 { margin:0 0 .3rem; font-size:.8rem; font-weight:650; color:__INK__; }
.gs-card .k { font-size:.72rem; color:__INK2__; }
.gs-card p { font-size:.79rem; color:__INK2__; line-height:1.55; margin:.2rem 0; }
.gs-two { display:grid; gap:.7rem;
  grid-template-columns:repeat(auto-fit,minmax(290px,1fr)); }
.gs-three { display:grid; gap:.7rem;
  grid-template-columns:repeat(auto-fit,minmax(235px,1fr)); }
table.gs { width:100%; border-collapse:collapse; font-size:.75rem; }
table.gs th { text-align:left; font-size:.63rem; letter-spacing:.07em;
  text-transform:uppercase; color:__MUTED__; font-weight:600;
  border-bottom:1px solid __RULE__; padding:.3rem .45rem; }
table.gs td { border-bottom:1px solid __LINE__; padding:.34rem .45rem;
  color:__INK2__; vertical-align:top; overflow-wrap:anywhere; }
table.gs td.num { text-align:right; font-variant-numeric:tabular-nums;
  color:__INK__; }
table.gs tr:last-child td { border-bottom:none; }
.bar { height:8px; border-radius:4px; background:__TRACK__; overflow:hidden;
  min-width:60px; }
.bar > i { display:block; height:100%; border-radius:4px; background:__BLUE__; }
.gs-wrap { overflow-x:auto; }

/* ---- the flow diagram ---------------------------------------------- */
.flow { display:grid; gap:.55rem; }
.node { background:__SURFACE__; border:1px solid __LINE__;
  border-left:3px solid __RULE__; border-radius:9px; padding:.55rem .7rem; }
.node.router { border-left-color:__VIOLET__; }
.node.reader { border-left-color:__AQUA__; }
.node.writer { border-left-color:__CRIT__; }
.node.human  { border-left-color:__SERIOUS__; }
.node .n { font-size:.82rem; font-weight:650; color:__INK__; }
.node .d { font-size:.72rem; color:__INK2__; line-height:1.45; margin-top:.15rem; }
.node .hits { float:right; font-size:.68rem; color:__INK2__;
  font-variant-numeric:tabular-nums; }
.arrow { text-align:center; color:__MUTED__; font-size:.72rem; line-height:1;
  margin:-.15rem 0; }
.fan { display:grid; gap:.55rem; margin-left:1.1rem;
  grid-template-columns:repeat(auto-fit,minmax(245px,1fr)); }

/* ---- the chat ------------------------------------------------------
   Not st.chat_message: that always draws left with an avatar, so both
   speakers come out identical. These are our own rows, and WHICH SIDE a
   bubble sits on is the fastest thing a reader can tell apart -- faster
   than an avatar, faster than a colour.                                */
.chat-wrap { display:flex; flex-direction:column;
  background:__SUNK__; border:1px solid __LINE__; border-radius:12px;
  padding:.8rem .8rem .6rem; min-height:460px; }
.chat-row { display:flex; gap:.45rem; margin:.28rem 0; align-items:flex-end; }
.chat-row.me   { justify-content:flex-end; }
.chat-row.desk { justify-content:flex-start; }
.chat-msg { max-width:80%; padding:.55rem .8rem; border-radius:15px;
  font-size:.87rem; line-height:1.6; overflow-wrap:anywhere; }
/* the customer is filled and on the right; the desk is outlined and on the
   left. The tail-corner on each says which way the message went. */
.chat-row.me .chat-msg { background:__BLUEINK__; color:#ffffff;
  border-bottom-right-radius:5px; }
.chat-row.desk .chat-msg { background:__SURFACE__; color:__INK__;
  border:1px solid __LINE__; border-bottom-left-radius:5px;
  box-shadow:__SHADOW__; }
.chat-av { width:27px; height:27px; flex:none; border-radius:50%;
  display:flex; align-items:center; justify-content:center; font-size:.86rem;
  background:__SURFACE__; border:1px solid __LINE__; }
.chat-div { text-align:center; font-size:.63rem; color:__MUTED__;
  letter-spacing:.1em; text-transform:uppercase; font-weight:600;
  margin:.8rem 0 .55rem; border-top:1px solid __LINE__; }
.chat-div span { position:relative; top:-.55rem; background:__SUNK__;
  padding:0 .6rem; }
.chat-empty { text-align:center; color:__MUTED__; font-size:.82rem;
  margin:auto; padding:1.8rem .5rem; line-height:1.6; }

/* ---- the desk while it is still working -----------------------------
   The step titles this is built from are internal labels -- "says",
   "returns" -- which tell a reader nothing. What goes on screen is a
   sentence about what is happening, and a counter that keeps moving so a
   slow turn is visibly alive rather than apparently hung.            */
.chat-msg.live { color:__INK2__; min-width:min(300px, 100%); }
.lwork { font-weight:700; color:__INK__; font-size:.82rem; }
.lstep { margin-top:.25rem; font-size:.81rem; color:__INK__; }
.lstep .who { font-weight:600; color:__VIOLETINK__; }
.lcount { margin-top:.3rem; font-size:.72rem; color:__MUTED__;
  font-variant-numeric:tabular-nums; }
.dots { display:inline-flex; gap:3px; margin-right:.4rem;
  vertical-align:middle; }
.dots i { width:5px; height:5px; border-radius:50%; background:__BLUEINK__;
  display:block; animation:gsblink 1.15s infinite ease-in-out; }
.dots i:nth-child(2) { animation-delay:.18s; }
.dots i:nth-child(3) { animation-delay:.36s; }
@keyframes gsblink { 0%,80%,100% { opacity:.22 } 40% { opacity:1 } }
/* Someone may have reduced motion at the OS level; the dots are decoration,
   so they simply stop rather than being the only thing carrying the state. */
@media (prefers-reduced-motion: reduce) {
  .dots i { animation:none; opacity:.55; }
}
.chat-err { margin-top:.4rem; font-size:.76rem; color:__CRITINK__;
  font-weight:600; }
.gs-meta { display:flex; flex-wrap:wrap; gap:.3rem; margin-top:.5rem;
  padding-top:.45rem; border-top:1px solid __LINE__; align-items:center; }
.gs-tkt { display:inline-block; font-size:.66rem; font-weight:600;
  padding:.14rem .45rem; border-radius:6px; border:1px solid __LINE__;
  background:__SUNK__; color:__INK2__; white-space:nowrap; }
.gs-tkt.ai    { border-color:__GOOD__;    color:__GOODINK__;    background:transparent; }
.gs-tkt.human { border-color:__SERIOUS__; color:__SERIOUSINK__; background:transparent; }
.gs-tkt.none  { border-color:__CRIT__;    color:__CRITINK__;    background:transparent; }
.gs-tkt.chased{ border-color:__ORANGE__;  color:__ORANGEINK__;  background:transparent; }
.gs-tkt.quiet { color:__MUTED__; background:transparent; font-weight:500; }
.gs-live { font-size:.8rem; color:__INK2__; line-height:1.6; }
.gs-live b { color:__INK__; font-weight:600; }

/* ---- the verdict banner ---------------------------------------------
   The one thing this whole app exists to show, so it is the largest thing
   in the column rather than a chip somewhere. Colour is doing a job here:
   green means a rule covered it, amber means a person now owns it, red
   means nothing was recorded at all.                                    */
.verdict { border:1px solid __LINE__; border-left:6px solid __RULE__;
  border-radius:11px; padding:.75rem .95rem .8rem; margin:.1rem 0 .7rem;
  background:__SURFACE__; box-shadow:__SHADOW__; }
.verdict .vk { font-size:.62rem; letter-spacing:.12em; text-transform:uppercase;
  color:__MUTED__; font-weight:700; }
.verdict .vfig { font-size:1.5rem; font-weight:700; line-height:1.2;
  margin:.15rem 0 .1rem; letter-spacing:-.01em; }
.verdict .vsub { font-size:.79rem; color:__INK2__; line-height:1.5; }
.verdict .vrow { margin-top:.55rem; padding-top:.5rem;
  border-top:1px solid __LINE__; font-size:.75rem; color:__INK2__;
  line-height:1.55; }
.verdict .vrow + .vrow { border-top:none; padding-top:.15rem; margin-top:.3rem; }
/* ENFORCED = it happens in Python and cannot not happen.
   REQUESTED = a sentence in a Skill, with a failure rate. */
.venf { display:inline-block; font-size:.6rem; font-weight:800;
  letter-spacing:.09em; padding:.1rem .4rem; border-radius:4px;
  margin-right:.4rem; color:#ffffff; background:__VIOLET__;
  vertical-align:.05rem; }
.venf.ask { background:__MUTED__; }
.verdict.human { border-left-color:__SERIOUS__; }
.verdict.human .vfig { color:__SERIOUSINK__; }
.verdict.ai    { border-left-color:__GOOD__; }
.verdict.ai .vfig { color:__GOODINK__; }
.verdict.none  { border-left-color:__CRIT__; }
.verdict.none .vfig { color:__CRITINK__; }
.verdict.idle  { border-left-color:__RULE__; }
.verdict.idle .vfig { color:__MUTED__; font-size:1.05rem; }

/* ---- streamlit chrome, kept in the same palette -------------------- */
.stTabs [data-baseweb="tab-list"] { gap:.15rem; border-bottom:1px solid __LINE__;
  flex-wrap:wrap; }
.stTabs [data-baseweb="tab"] { font-size:.78rem; padding:.35rem .7rem; }
[data-testid="stExpander"] { border:1px solid __LINE__; border-radius:9px;
  background:__SURFACE__; }
code, .stCode { font-size:.73rem !important; }

/* ---- small screens: nothing overflows, everything stacks ----------- */
@media (max-width: 720px) {
  .block-container { padding-left:.7rem; padding-right:.7rem; }
  .gs-grid { grid-template-columns:repeat(auto-fit,minmax(126px,1fr)); }
  .gs-tile .val { font-size:1.15rem; }
  .gs-hero .fig { font-size:2.1rem; }
  .gs-mast { padding:1.1rem 1.05rem .95rem; }
  .gs-mast h1 { font-size:1.85rem; }
  .fan { margin-left:0; }
}
</style>
"""


def paint() -> None:
    """Substitute the one palette into the stylesheet. No mode argument,
    because there is no mode."""
    css = CSS
    for key, value in PALETTE.items():
        css = css.replace(f"__{key}__", value)
    st.markdown(css, unsafe_allow_html=True)


# ==========================================================================
# 3. READING THE STREAM
#    The SDK yields typed objects. Everything this app shows is derived here
#    and nowhere else -- no second source of truth, and no guessing.
# ==========================================================================

def jsonable(obj, depth=0):
    """Any SDK object -> plain JSON, for the RAW JSON tab and the downloads.

    Recursive rather than repr(): the raw tab is meant to be diffable and
    searchable, and a repr string is neither.
    """
    if depth > 14:
        return str(obj)
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, dict):
        return {str(k): jsonable(v, depth + 1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [jsonable(v, depth + 1) for v in obj]
    if is_dataclass(obj) and not isinstance(obj, type):
        out = {"__type__": type(obj).__name__}
        for f in fields(obj):
            out[f.name] = jsonable(getattr(obj, f.name, None), depth + 1)
        return out
    if hasattr(obj, "__dict__"):
        out = {"__type__": type(obj).__name__}
        for k, v in vars(obj).items():
            out[k] = jsonable(v, depth + 1)
        return out
    return str(obj)


def short(text, limit=260):
    text = str(text).replace("\n", " ").strip()
    return text if len(text) <= limit else f"{text[:limit]} ... (+{len(text)-limit} chars)"


def tool_kind(name: str) -> str:
    """What a tool call actually DOES -- the one thing the name alone hides.

    A write looks exactly like a read in the stream. Only the tool name and
    who called it tell them apart, so the classification happens once, here,
    and every tile and table downstream reads this instead of re-deciding.
    """
    if name in DELEGATE_TOOLS:
        return "delegate"
    if name.endswith(WRITE_TOOLS):
        return "write"
    if "add_rows" in name:
        return "blank"        # inserts an EMPTY row: writes no ticket
    if name.startswith("mcp__sheets__"):
        return "read"
    if name == "Skill":
        return "skill"
    return "internal"


KIND_STYLE = {
    "delegate": ("deleg", "router", "DELEGATION"),
    "write":    ("write", "write",  "SHEET WRITE"),
    "blank":    ("err",   "bad",    "BLANK ROW"),
    "read":     ("read",  "read",   "SHEET READ"),
    "skill":    ("sys",   "sdk",    "SKILL LOAD"),
    "internal": ("sys",   "sdk",    "SDK INTERNAL"),
}


def blank_run(question: str = "") -> dict:
    """Everything one Send produces. Per-QUESTION counters live here."""
    return {
        "question": question,
        "started": None, "finished": None, "error": None,
        "steps": [],          # the timeline
        "raw": [],            # jsonable messages, in arrival order
        "calls": [],          # one record per ToolUseBlock, result paired in
        "convos": [],         # one record per ResultMessage
        "inits": [],          # every SystemMessage init payload
        "who_by_task": {},    # Agent tool_use id -> subagent name
        "open_calls": {},     # tool_use id -> index into calls
        "delegations": 0, "reads": 0, "writes": 0, "messages": 0,
        "hits": {name: 0 for name in SUBAGENTS},
        "tables": [],         # sheet rows the specialists actually read back
        "row": [], "reply": "", "reports": [],
        "server": "--", "skill_pending": False,
        "webhook": None,      # {"status":..., "payload":...} once posted
        "slack": None,        # {"ok":..., "detail":..., "channel":...} likewise
        "second_ticket": None,
        "ticket_chased": False,   # True if PYTHON had to ask for the ticket
        "ticket_existing": "",    # a ticket that was ALREADY on the sheet
        "ticket_unverified": False,   # ...claimed, but not seen in a read
        "handoff_skipped": "",    # why no webhook/Slack went out
    }


def add_step(run, kind, title, agent="", body="", mono="", tone=""):
    run["steps"].append({
        "i": len(run["steps"]) + 1,
        "at": time.time() - (run["started"] or time.time()),
        "kind": kind, "title": title, "agent": agent,
        "body": body, "mono": mono, "tone": tone,
    })


def note_ticket(run, tool_input) -> None:
    """Read the ticket off the row the ticket-writer is ACTUALLY sending.

    update_cells carries the row as `data`; batch_update_cells nests it one
    level under `ranges`. A Skill ORDERS a ticket, and a Skill is a REQUEST --
    this is where you find out whether it was honoured.
    """
    cells = tool_input.get("data") or next(
        iter((tool_input.get("ranges") or {}).values()), [])
    # A ticket row is 5 wide: Ticket ID | Order ID | Issue | Resolution | Action By
    row = next((r for r in cells if isinstance(r, list) and len(r) >= 5), [])
    if not row:
        return
    new_row = [str(c) for c in row[:5]]

    # One ticket per conversation. If a second, different ticket ID shows up,
    # say so rather than quietly overwriting the tile and leaving two rows in
    # the sheet for someone to find later.
    old = run["row"]
    if old and old[0] and new_row[0] != old[0]:
        run["second_ticket"] = (old[0], new_row[0])
        add_step(run, "err", f"SECOND TICKET in one conversation: {old[0]} "
                             f"already existed and the agent wrote {new_row[0]}",
                 agent="ticket-writer",
                 body="The Skill asked for one ticket per conversation and it "
                      "did not comply. Delete the extra row.")
    run["row"] = new_row


TICKET_ID_RE = r"\bTKT-\d{1,6}\b"


def note_existing_ticket(run) -> None:
    """A run can end with no write and still have a ticket -- because the row
    was already there.

    ticket-writer/SKILL.md tells it not to add a duplicate for the same order
    and issue, and to report the existing id instead. When it obeys, nothing
    is written, so `note_ticket` sees nothing and the page says NO TICKET --
    which is the opposite of the truth and the worst thing this app could say.

    But a reported id is a CLAIM. So it is checked against the Tickets rows
    the specialist actually read back: if that id is in the grid it saw, the
    row is real and we take Action By off the SHEET rather than off the
    sentence. If it is not, the claim is kept and flagged, never promoted.
    """
    if run["row"] or not run["reports"]:
        return
    found = re.findall(TICKET_ID_RE, " ".join(run["reports"]))
    if not found:
        return
    claimed = found[-1]
    for grab in run["tables"]:
        for row in grab["rows"]:
            if row and str(row[0]).strip() == claimed and len(row) >= 5:
                run["row"] = [str(c) for c in row[:5]]
                run["ticket_existing"] = claimed
                add_step(run, "done", f"ticket {claimed} was ALREADY on the "
                                      f"sheet -- no second row written",
                         agent="ticket-writer",
                         body="One conversation is one case. The row was read "
                              "back in this run, so Action By below is the "
                              "sheet's own value, not a claim.")
                return
    run["ticket_existing"] = claimed
    run["ticket_unverified"] = True
    add_step(run, "err", f"the desk says ticket {claimed} already exists, but "
                         f"no Tickets row was read back to confirm it",
             agent="ticket-writer",
             body="Reported, not verified. The id is shown as a claim and "
                  "nothing is filled in from it.")


def ingest(run, message) -> None:
    """One SDK message -> tiles, timeline, tool table, cost table, raw JSON."""
    run["messages"] += 1
    run["raw"].append(jsonable(message))

    if isinstance(message, SystemMessage):
        data = getattr(message, "data", None) or {}
        if getattr(message, "subtype", "") == "init":
            run["inits"].append(data)
            first = len(run["inits"]) == 1
            if first:
                # Only the FIRST init is the router's. Everything the session
                # was actually given, checked rather than assumed.
                loaded = data.get("skills", []) or []
                registered = data.get("agents", []) or []
                missing_skills = [s for s in OUR_SKILLS if s not in loaded]
                missing_agents = [a for a in SUBAGENTS if a not in registered]
                servers = data.get("mcp_servers", []) or []
                sheets = next((s for s in servers
                               if s.get("name") == "sheets"), None)
                run["server"] = str(sheets.get("status")) if sheets else "pending"
                lines = [
                    f"skills loaded: {len(OUR_SKILLS) - len(missing_skills)}/"
                    f"{len(OUR_SKILLS)}" + (f"  MISSING {missing_skills}"
                                            if missing_skills else ""),
                    f"subagents registered: {len(SUBAGENTS) - len(missing_agents)}"
                    f"/{len(SUBAGENTS)}" + (f"  MISSING {missing_agents}"
                                            if missing_agents else ""),
                    f"mcp server 'sheets': {run['server']}",
                    f"model: {data.get('model', MODEL)}",
                    f"tools in session: {len(data.get('tools', []) or [])}",
                ]
                add_step(run, "sys", "SDK session started", agent="router",
                         body="  ·  ".join(lines))
                if run["server"] in ("failed", "needs-auth"):
                    add_step(run, "err",
                             f"the sheets server is {run['server']}",
                             body="Check SERVICE_ACCOUNT_PATH and that the "
                                  "sheet is shared with the service account "
                                  "as an EDITOR -- this day writes.")
            else:
                # A specialist just opened a session of its OWN. That separate
                # session IS the lesson, so it gets a line of its own.
                add_step(run, "sys", "a specialist opened its OWN session",
                         body="No history, only the prompt it was handed -- and "
                              "only its final text comes back. The router never "
                              "sees its raw tool results.")
        return

    if isinstance(message, (AssistantMessage, UserMessage)):
        who = run["who_by_task"].get(
            getattr(message, "parent_tool_use_id", None) or "", "")
        walk_blocks(run, getattr(message, "content", None), who)
        return

    if isinstance(message, ResultMessage):
        note_result(run, message)


def walk_blocks(run, content, who) -> None:
    """Walk one message's content blocks.

    An Agent call is a DELEGATION. Everything printed after it, until the
    result comes back, happened inside that specialist's own conversation and
    carries that call's id as parent_tool_use_id -- which is how `who` above
    is a lookup rather than a guess.
    """
    if not content or isinstance(content, str):
        return
    speaker = who or "router"

    for block in content:
        if isinstance(block, TextBlock):
            # The turn right after a Skill call is SKILL.md being read back --
            # already on screen in the AGENTS tab, so it is not repeated here.
            if run["skill_pending"]:
                run["skill_pending"] = False
                add_step(run, "sys", "SKILL.md read back", agent=speaker)
                continue
            if not block.text.strip():
                continue
            add_step(run, "text", "says", agent=speaker, tone="said",
                     body=block.text.strip())
            # Keep it for the handoff. The router's last line is what the
            # customer heard; a specialist's is where the email lives.
            if who:
                run["reports"].append(block.text.strip())
            else:
                run["reply"] = block.text.strip()

        elif isinstance(block, ToolUseBlock):
            kind = tool_kind(block.name)
            run["skill_pending"] = block.name == "Skill"
            record = {
                "n": len(run["calls"]) + 1, "id": block.id, "name": block.name,
                "kind": kind, "agent": speaker, "input": jsonable(block.input),
                "started": time.time(), "at": time.time() - (run["started"] or time.time()),
                "result": None, "is_error": None, "ms": None,
            }
            run["calls"].append(record)
            run["open_calls"][block.id] = len(run["calls"]) - 1
            step_kind, _, label = KIND_STYLE[kind]

            if kind == "delegate":
                run["delegations"] += 1
                target = block.input.get("subagent_type", "?")
                run["who_by_task"][block.id] = target
                if target in run["hits"]:
                    run["hits"][target] += 1
                # This prompt IS the context being passed. A subagent shares no
                # memory with the router, so whatever is not written here is
                # not known -- which is why the order ID gets repeated by hand.
                add_step(run, step_kind,
                         f"DELEGATION {run['delegations']}  ->  {target}",
                         agent=speaker,
                         body="hands down the whole context, because a subagent "
                              "shares no memory with the router:",
                         mono=short(block.input.get("prompt", ""), 700))
            elif kind == "write":
                run["writes"] += 1
                note_ticket(run, block.input)
                add_step(run, step_kind, f"{label}  {block.name}", agent=speaker,
                         body="values go into cells -- this is the consequential "
                              "call in the whole run",
                         mono=short(json.dumps(record["input"], default=str), 700))
            elif kind == "blank":
                run["reads"] += 1
                add_step(run, step_kind, f"{label}  {block.name}", agent=speaker,
                         body="add_rows takes a row COUNT, not values: it inserts "
                              "a BLANK row and writes no ticket. A run that stops "
                              "here has recorded nothing.",
                         mono=short(json.dumps(record["input"], default=str), 400))
            elif kind == "read":
                run["reads"] += 1
                add_step(run, step_kind, f"{label}  {block.name}", agent=speaker,
                         body="the specialist picked this tool itself -- nobody "
                              "named it in the code",
                         mono=short(json.dumps(record["input"], default=str), 400))
            else:
                add_step(run, step_kind, f"{label}  {block.name}", agent=speaker)

        elif isinstance(block, ToolResultBlock):
            index = run["open_calls"].pop(getattr(block, "tool_use_id", ""), None)
            text = block.content if isinstance(block.content, str) else \
                json.dumps(jsonable(block.content), default=str)
            if index is not None:
                call = run["calls"][index]
                call["result"] = text
                call["is_error"] = bool(block.is_error)
                call["ms"] = round((time.time() - call["started"]) * 1000)
                # A sheet read that came back clean is proof the server
                # finished connecting -- the init snapshot often says
                # "pending" because it connects in the background.
                if call["kind"] in ("read", "write") and not block.is_error:
                    if run["server"] != "connected":
                        run["server"] = "connected"
                    capture_table(run, call, text)
            if run["skill_pending"]:
                continue
            flag = "  [is_error]" if block.is_error else ""
            add_step(run, "err" if block.is_error else "sys",
                     f"returns{flag}", agent=who or "router", mono=short(text, 500))


def find_rows(value, depth=0):
    """Dig a list-of-lists out of whatever the sheets server sent back.

    Different tools wrap the grid differently (`values`, `data`, a bare list,
    or a text block holding JSON), so this looks for the SHAPE rather than
    trusting any one key.
    """
    if depth > 6:
        return None
    if isinstance(value, list):
        if value and all(isinstance(r, list) for r in value):
            return value
        for item in value:
            found = find_rows(item, depth + 1)
            if found:
                return found
        return None
    if isinstance(value, dict):
        for key in ("values", "data", "rows", "result", "content", "text"):
            if key in value:
                found = find_rows(value[key], depth + 1)
                if found:
                    return found
        for item in value.values():
            found = find_rows(item, depth + 1)
            if found:
                return found
        return None
    if isinstance(value, str) and value.strip()[:1] in ("[", "{"):
        try:
            return find_rows(json.loads(value), depth + 1)
        except (ValueError, TypeError):
            return None
    return None


def capture_table(run, call, text) -> None:
    """Keep the sheet rows a specialist actually read back.

    This is the only honest way to show "the data": not a second read of our
    own from a different credential, but the exact bytes the agent saw.
    """
    rows = find_rows(text)
    if not rows:
        return
    rows = [[("" if c is None else str(c)) for c in r] for r in rows[:60]]
    run["tables"].append({
        "call": call["n"], "agent": call["agent"], "tool": call["name"],
        "args": call["input"], "rows": rows,
    })


def note_result(run, message) -> None:
    """EVERY conversation ends with one of these -- each specialist's as well
    as the router's. Tokens are per-conversation and all billed, so they add
    up. total_cost_usd does NOT: it is a RUNNING TOTAL that arrives strictly
    increasing, and the router's final one covers the whole question. Summing
    them triple-counts the bill."""
    usage = getattr(message, "usage", None) or {}
    run["convos"].append({
        "n": len(run["convos"]) + 1,
        "session_id": getattr(message, "session_id", "") or "",
        "subtype": getattr(message, "subtype", "") or "",
        "terminal_reason": getattr(message, "terminal_reason", None),
        "is_error": bool(getattr(message, "is_error", False)),
        "num_turns": getattr(message, "num_turns", None),
        "duration_ms": getattr(message, "duration_ms", None),
        "duration_api_ms": getattr(message, "duration_api_ms", None),
        "in": usage.get("input_tokens", 0) or 0,
        "out": usage.get("output_tokens", 0) or 0,
        "cache_read": usage.get("cache_read_input_tokens", 0) or 0,
        "cache_write": usage.get("cache_creation_input_tokens", 0) or 0,
        "running_cost": getattr(message, "total_cost_usd", None) or 0.0,
        "at": time.time() - (run["started"] or time.time()),
    })
    add_step(run, "done", f"conversation {len(run['convos'])} ended",
             body=f"turns {getattr(message, 'num_turns', '?')}  ·  "
                  f"reason {getattr(message, 'terminal_reason', None) or getattr(message, 'subtype', '?')}"
                  f"  ·  running cost ${getattr(message, 'total_cost_usd', 0) or 0:.4f}")


def verdict(run):
    """The LAST ResultMessage is the whole question's. Nested ones end each
    specialist's conversation and would paint the tiles three times."""
    return run["convos"][-1] if run["convos"] else None


def total_cost(run) -> float:
    # Not a sum. See note_result: the values are a running total.
    return max((c["running_cost"] for c in run["convos"]), default=0.0)


def action_by(run):
    """The ticket's fifth column, and whether the sheet will accept it."""
    if not run["row"]:
        return "", False
    value = run["row"][4]
    return value, value in (ACTED_BY_AI, ACTED_BY_HUMAN)


# Bounded quantifiers, and no two parts able to match the same text: these
# strings are model output and customer input of unknown length, and an
# ambiguous pattern on those is a hang, not a bad match.
EMAIL_RE = r"[\w.+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{1,63}){1,4}"


def escalation_payload(run) -> dict:
    """The structured handoff. The supervisor has no transcript and about
    eleven seconds, so everything they need is on one screen of JSON."""
    row = run["row"] or ["", "", "", "", ""]
    # The specialist's report first -- that is the address ON the order. Then
    # the customer's own messages, because an order that is not in the sheet
    # has no row to read an address off, and the router now asks them for one.
    # Their answer is the only contact detail that will ever exist for it.
    found = re.search(EMAIL_RE, " ".join(run["reports"])) or \
        re.search(EMAIL_RE, " ".join(st.session_state.get("questions", [])))
    end = verdict(run)
    return {
        "ticket_id": row[0], "order_id": row[1], "issue": row[2],
        "resolution": row[3], "action_by": row[4],
        # BEST EFFORT: the email is not one of the five ticket columns, so it
        # is matched out of the specialist's report. Null rather than invented.
        "customer_email": found.group(0) if found else None,
        "customer_questions": st.session_state.get("questions", []),
        "agent_reply": run["reply"], "specialist_reports": run["reports"],
        "delegations": run["delegations"],
        "sheet_reads": run["reads"], "sheet_writes": run["writes"],
        "turns": end["num_turns"] if end else None,
        "cost_usd": round(total_cost(run), 4),
        "raised_at": datetime.now().isoformat(timespec="seconds"),
    }


def post_escalation(run) -> None:
    """Hand the case to whoever works the queue.

    PYTHON sends this, not an agent. A Skill saying "notify a human" is a
    request with a failure rate; `if action_by == Human` is not. And the agent
    never gets a "POST anywhere" tool -- destination and payload shape are
    both fixed here, so a confused model cannot mail your customer list to an
    address it invented.
    """
    payload = escalation_payload(run)
    if not WEBHOOK_URL:
        run["webhook"] = {"status": "not configured", "ok": False,
                          "payload": payload,
                          "detail": "ESCALATION_WEBHOOK_URL is missing from "
                                    ".env -- the ticket exists, nobody was told."}
        return
    request = urllib.request.Request(
        WEBHOOK_URL, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            run["webhook"] = {"status": str(response.status), "ok": True,
                              "payload": payload, "detail": "escalation delivered"}
    except OSError as exc:      # URLError and HTTPError both derive from this
        # The ticket row survives either way, but a silently dropped webhook
        # means a case no human is ever told about. Make it loud.
        run["webhook"] = {"status": "FAILED", "ok": False, "payload": payload,
                          "detail": f"{exc} -- the ticket exists, but nobody "
                                    f"has been notified. Chase it by hand."}


def slack_message(run) -> dict:
    """The card that lands in the channel.

    Written for someone glancing at a phone: the ticket id and the order first,
    then what the customer asked and what a person now has to decide. `text` is
    not decoration -- it is what Slack puts in the notification and in the
    sidebar preview, so it has to stand alone without the blocks.
    """
    payload = escalation_payload(run)
    ticket = payload["ticket_id"] or "(no id)"
    order = payload["order_id"] or "unknown"
    email = payload["customer_email"] or "not on the order"
    fields = [
        ("Ticket", ticket), ("Order", order),
        ("Owner", payload["action_by"] or "--"), ("Contact", email),
    ]
    blocks = [
        {"type": "header",
         "text": {"type": "plain_text", "text": f"Escalation · {ticket}"}},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*{k}*{chr(10)}{v}"} for k, v in fields]},
        {"type": "section", "text": {"type": "mrkdwn", "text":
            f"*Issue*{chr(10)}{payload['issue'] or '--'}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text":
            f"*A person must decide*{chr(10)}{payload['resolution'] or '--'}"}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text":
            f"raised {payload['raised_at']} · {payload['delegations']} "
            f"delegation(s) · ${payload['cost_usd']:.4f}"
            + (f" · <{SHEET_URL}|open the sheet>" if SHEET_URL else "")}]},
    ]
    return {
        "channel": SLACK_CHANNEL_ID,
        "text": f"Escalation {ticket} · order {order} · a person must decide: "
                f"{payload['resolution'] or 'see the ticket'}",
        "blocks": blocks,
        "unfurl_links": False,
    }


def post_slack(run) -> None:
    """Put the case in the team's Slack channel. Python sends it, not an agent.

    THE TRAP, and it is the whole reason this is not a copy of
    post_escalation: Slack answers HTTP 200 on failure. A bad token, a channel
    the bot was never invited to, a missing scope -- all of them come back
    200 with `{"ok": false, "error": "..."}` in the body. Checking the status
    code alone gives you a handoff that reports success every single time and
    delivers nothing, which is worse than no handoff at all, because now
    nobody is watching for it either.

    So: read `ok` out of the body, and put `error` on screen verbatim.
    """
    if not SLACK_BOT_TOKEN or not SLACK_CHANNEL_ID:
        missing = " and ".join(
            n for n, v in (("SLACK_BOT_TOKEN", SLACK_BOT_TOKEN),
                           ("SLACK_CHANNEL_ID", SLACK_CHANNEL_ID)) if not v)
        run["slack"] = {"ok": False, "status": "not configured",
                        "channel": SLACK_CHANNEL_ID or "--",
                        "detail": f"{missing} missing from .env -- the ticket "
                                  f"exists and nobody was pinged."}
        return

    body = slack_message(run)
    request = urllib.request.Request(
        SLACK_API_URL, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8",
                 "Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
        method="POST")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            answer = json.loads(response.read().decode("utf-8") or "{}")
    except OSError as exc:          # URLError and HTTPError both derive here
        run["slack"] = {"ok": False, "status": "FAILED",
                        "channel": SLACK_CHANNEL_ID, "payload": body,
                        "detail": f"{exc} -- the ticket exists, but the "
                                  f"channel was not told. Chase it by hand."}
        return

    if answer.get("ok"):
        run["slack"] = {"ok": True, "status": "posted",
                        "channel": answer.get("channel", SLACK_CHANNEL_ID),
                        "ts": answer.get("ts", ""), "payload": body,
                        "detail": "delivered to the channel"}
        return

    # HTTP 200, and it still did not arrive. Say which of the usual four it is.
    code = str(answer.get("error", "unknown_error"))
    hint = {
        "invalid_auth": "the token is wrong or revoked",
        "not_authed": "no token was sent",
        "account_inactive": "the app was removed from the workspace",
        "channel_not_found": "SLACK_CHANNEL_ID does not exist in this "
                             "workspace -- check you copied the ID (C...) and "
                             "not the name",
        "not_in_channel": "the bot is not in that channel -- invite it, or add "
                          "the chat:write.public scope",
        "missing_scope": "the token lacks chat:write",
        "is_archived": "that channel is archived",
        "ratelimited": "too many posts, back off and retry",
    }.get(code, "see Slack's chat.postMessage error list")
    run["slack"] = {"ok": False, "status": f"ok:false · {code}",
                    "channel": SLACK_CHANNEL_ID, "payload": body,
                    "detail": f"Slack answered HTTP 200 and did NOT post: "
                              f"{code} -- {hint}."}


# ==========================================================================
# 4. THE RUN -- one `async for` over the SDK's stream, on a worker thread.
#    No loop of ours: the SDK's loop decides how many turns the question
#    needs, and this just reads what it produces.
# ==========================================================================

def start_worker(question, resume, max_turns, max_output, model):
    events = queue.Queue()

    async def drive():
        async for message in query(
                prompt=question,
                options=build_options(resume, max_turns, max_output, model)):
            events.put(("msg", message))

    def worker():
        try:
            asyncio.run(drive())
        except Exception as exc:                    # noqa: BLE001 -- shown in UI
            events.put(("error", exc))
        events.put(("done", None))

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return events, thread


# The nudge is addressed to the ROUTER, in the router's own vocabulary, and it
# repeats the two dropdown spellings rather than trusting them to be recalled.
# It is deliberately NOT phrased as a customer message: the desk must not
# answer it as if someone had written in.
TICKET_NUDGE = f"""SYSTEM CHECK -- this is not a message from the customer, and it needs no reply to them.

This conversation has no row in the Tickets tab. Every case gets exactly one, including the dull ones -- a case with no ticket is one nobody can audit. File it now.

Call ticket-writer once, with:
  - the order ID discussed above, or exactly `not_given` if the customer never supplied one
  - Issue: one line, in the customer's terms
  - Resolution: one line -- what you told them, or what a person must still decide
  - Action By: exactly `{ACTED_BY_AI}` or exactly `{ACTED_BY_HUMAN}`. If the case was NOT resolved -- no rule covered it, the order was not_found, a specialist errored, or you could not finish -- it is `{ACTED_BY_HUMAN}`.

Then reply with the ticket ID and nothing else."""


def chase_missing_ticket(run, session_id, max_turns, max_output, model,
                         live=None, stream=None) -> bool:
    """Make the ticket a guarantee instead of a request.

    support-router/SKILL.md ORDERS exactly one ticket per conversation. A
    Skill is a REQUEST with a non-zero failure rate -- that is the whole
    lesson of the day, and it applies to the instruction that produces the
    audit trail just as much as to the ones about which tab to read.

    So Python checks. If the stream ended with no write, it asks ONCE, in the
    same session, and the follow-up's tool calls are ingested into the same
    run -- they really happened, so they belong in the tables and in the bill.

    Not a loop. One ask. If the agent still will not file a row, the chat says
    so in red rather than quietly pretending a case was recorded.
    """
    if run["row"] or not session_id:
        return bool(run["row"])

    run["ticket_chased"] = True
    add_step(run, "err", "the run ended with NO ticket -- asking once, in code",
             body="A Skill is a request. This is the check that turns it into "
                  "a guarantee: one explicit follow-up on the same session.")
    if live:
        live.markdown('<div class="gs-live"><b>No ticket was filed.</b> '
                      'Asking the desk once, explicitly...</div>',
                      unsafe_allow_html=True)

    # The customer-facing reply belongs to the customer's question, not to
    # this housekeeping turn. Put it back afterwards.
    saved_reply = run["reply"]
    events, _ = start_worker(TICKET_NUDGE, session_id, max_turns,
                             max_output, model)
    deadline, finished = time.time() + 300, False
    while not finished and time.time() < deadline:
        try:
            kind, item = events.get(timeout=0.25)
        except queue.Empty:
            continue
        if kind == "msg":
            ingest(run, item)
            if isinstance(item, ResultMessage) and getattr(item, "session_id", None):
                run["chase_session"] = item.session_id
        elif kind == "error":
            add_step(run, "err", "the ticket follow-up failed", body=str(item))
        elif kind == "done":
            finished = True
        if stream:
            stream.markdown(steps_html(run, tail=60), unsafe_allow_html=True)
    if saved_reply:
        run["reply"] = saved_reply
    if not finished:
        add_step(run, "err", "the ticket follow-up timed out")
    return bool(run["row"])


def execute_turn(question, resume, repaint, tiles_slot, live_slot,
                 stream_slot) -> dict:
    """Run ONE customer message to completion, painting as the stream arrives.

    This runs INSIDE the Run tab rather than after the whole page, and that is
    the only reason the chat does not blink. Streamlit reruns once when the
    input is submitted -- unavoidable, that is how a widget reports a value --
    and everything from there happens in that same pass: the bubble fills in,
    and by the time the other ten tabs draw, this has already returned, so
    they draw from the finished run instead of from the previous one.

    The old shape ran the agent after the page and called st.rerun() twice.
    That is what made it look like a form submit rather than a chat.
    """
    run = blank_run(question)
    run["started"] = time.time()
    add_step(run, "sys", "starting the SDK query",
             body=f"model {MODEL} · max_turns {state['max_turns']} · "
                  f"{'resuming ' + resume[:8] if resume else 'new session'}")

    def paint_live():
        # The thread is repainted as a whole, with the in-flight bubble on the
        # end. That is what lets it settle into the finished reply in place.
        repaint(live_bubble_html(run))
        who, what = live_status(run)
        doing = run["steps"][-1]["title"] if run["steps"] else "working"
        live_slot.markdown(
            f'<div class="gs-live">'
            f'<span class="dots"><i></i><i></i><i></i></span>'
            f'<b>{escape((who + " · " if who else "") + what)}</b><br>'
            f'<span style="font-size:.72rem">{escape(short(doing, 80))}</span>'
            f'</div>', unsafe_allow_html=True)

    tiles_slot.markdown(tiles_html(run), unsafe_allow_html=True)
    paint_live()

    events, _ = start_worker(question, resume, state["max_turns"],
                             state["max_output"], MODEL)
    deadline, finished = time.time() + 900, False
    while not finished:
        drained = 0
        while True:
            try:
                kind, item = events.get_nowait()
            except queue.Empty:
                break
            drained += 1
            if kind == "msg":
                ingest(run, item)
                if isinstance(item, ResultMessage) and getattr(item, "session_id", None):
                    # Nested conversations carry their own ids; the LAST is the
                    # router's, and that is the one the next message resumes.
                    state["session_id"] = item.session_id
            elif kind == "error":
                run["error"] = f"{type(item).__name__}: {item}"
                add_step(run, "err", "the run failed", body=str(item))
            elif kind == "done":
                finished = True

        tiles_slot.markdown(tiles_html(run), unsafe_allow_html=True)
        stream_slot.markdown(steps_html(run, tail=60), unsafe_allow_html=True)
        paint_live()
        if finished:
            break
        if time.time() > deadline:
            run["error"] = "timed out after 15 minutes"
            add_step(run, "err", "timed out waiting for the SDK")
            break
        time.sleep(0.12 if drained else 0.25)

    run["finished"] = time.time()

    # THE TICKET GUARANTEE, and the order of these three matters.
    #
    #   1. make sure a ticket exists     -- a Skill asked; this checks
    #   2. THEN read Action By off it    -- a chased row still decides the
    #                                       handoff, so it cannot come first
    #   3. THEN notify, if it says Human
    # A duplicate the writer declined to file is still a ticket. Find it
    # before deciding anything is missing.
    note_existing_ticket(run)

    if state.get("guarantee_ticket") and not run["row"] and not run["error"]:
        chase_missing_ticket(run, state["session_id"], state["max_turns"],
                             state["max_output"], MODEL,
                             live=live_slot, stream=stream_slot)
        if run.get("chase_session"):
            state["session_id"] = run["chase_session"]
        # The chase is usually what surfaces the duplicate, so look again.
        note_existing_ticket(run)

    who, valid = action_by(run)
    if valid and who == ACTED_BY_HUMAN:
        if run["ticket_existing"]:
            # Already raised. A handoff that fires again every time the same
            # customer asks again is one nobody reads -- the same reason it
            # does not fire on every ticket in the first place.
            run["handoff_skipped"] = run["ticket_existing"]
        else:
            # Two destinations, one condition, both in Python. The workflow
            # gets the structured payload; the channel gets the people who
            # work it.
            post_escalation(run)
            post_slack(run)

    stream_slot.markdown(steps_html(run), unsafe_allow_html=True)
    tiles_slot.markdown(tiles_html(run), unsafe_allow_html=True)
    live_slot.empty()
    return run


# ==========================================================================
# 5. RENDERING -- plain HTML against the palette tokens, so a colour is
#    changed in one place and nothing is coloured by hand.
# ==========================================================================

def tile(label, value, tone="", hint="", small=False) -> str:
    return (f'<div class="gs-tile {tone}"><span class="lab">{escape(label)}</span>'
            f'<div class="val{" sm" if small else ""}">{escape(str(value))}</div>'
            f'{f"<span class=hint>{escape(hint)}</span>" if hint else ""}</div>')


def turn_meta_html(turn) -> str:
    """The strip under one desk reply: the ticket, who owned it, whether
    Python had to ask twice, and whether anybody was actually notified.

    This is the chat's version of the two tiles worth reading first. A bubble
    with no badge would look like a finished case; a bubble that says NO
    TICKET says the opposite, loudly.
    """
    ticket = turn.get("ticket", "")
    who, valid = turn.get("action_by", ""), turn.get("valid")
    bits = []
    if not ticket:
        bits.append('<span class="gs-tkt none">NO TICKET -- nothing to audit</span>')
    else:
        klass = ("ai" if who == ACTED_BY_AI else
                 "human" if who == ACTED_BY_HUMAN else "none")
        bits.append(f'<span class="gs-tkt {klass}">{escape(ticket)} &nbsp;·&nbsp; '
                    f'{escape(who or "?")}</span>')
        if not valid:
            bits.append('<span class="gs-tkt none">not a dropdown value -- '
                        'will not filter</span>')
    if turn.get("existing"):
        bits.append('<span class="gs-tkt chased">already filed -- no new row'
                    '</span>')
    if turn.get("unverified"):
        bits.append('<span class="gs-tkt none">reported, not verified</span>')
    if turn.get("chased") and not turn.get("existing"):
        bits.append('<span class="gs-tkt chased">filed on the second ask</span>')
    hook = turn.get("webhook")
    if hook:
        bits.append(f'<span class="gs-tkt {"ai" if hook.get("ok") else "none"}">'
                    f'handoff {escape(str(hook.get("status")))}</span>')
    slack = turn.get("slack")
    if slack:
        bits.append(f'<span class="gs-tkt {"ai" if slack.get("ok") else "none"}">'
                    f'slack {escape(str(slack.get("status")))}</span>')
    bits.append(f'<span class="gs-tkt quiet">{turn.get("delegations", 0)} '
                f'delegation(s) &nbsp;·&nbsp; ${turn.get("cost", 0):.4f}</span>')
    return f'<div class="gs-meta">{"".join(bits)}</div>'


def clear_case() -> None:
    """End the conversation and start a fresh case.

    One place, because there are two Clear buttons -- one in the sidebar and
    one under the transcript -- and two of these drifting apart would mean a
    Clear that looks like it worked while the agent quietly resumes the old
    session and updates the old ticket.
    """
    state["run"] = blank_run()
    state["history"] = []
    state["session_id"] = None
    state["questions"] = []
    state["chat"] = []


def last_verdict_turn(chat):
    """The most recent desk reply that reached a verdict."""
    for turn in reversed(chat or []):
        if turn.get("role") == "assistant" and "ticket" in turn:
            return turn
    return None


def case_banner_working_html() -> str:
    """The banner during a turn. An empty gap where the verdict lives reads as
    "no answer"; this says the answer is still being decided."""
    return ('<div class="verdict idle"><span class="vk">who owns this case'
            '</span><div class="vfig">'
            '<span class="dots"><i></i><i></i><i></i></span>deciding…</div>'
            '<div class="vsub">The desk is still working. Whether a rule '
            'covers this case -- or a person has to decide it -- is not known '
            'until the ticket is written.</div></div>')


def case_banner_html(turn) -> str:
    """WHO OWNED THIS CASE, said as loudly as the column can say it.

    Underneath it, what was ENFORCED against what was merely REQUESTED --
    the distinction the whole day is built on. A Skill asking for a ticket is
    a request with a failure rate. `if action_by == Human: post_escalation()`
    is not: it is an if-statement, it runs every time, and the model is never
    handed a tool that could skip it.
    """
    if turn is None:
        return ('<div class="verdict idle"><span class="vk">who owns this case'
                '</span><div class="vfig">nothing asked yet</div>'
                '<div class="vsub">Every conversation ends with a ticket, and '
                'that ticket says whether a rule covered the case or a person '
                'has to decide it.</div></div>')

    ticket = turn.get("ticket") or ""
    who, valid = turn.get("action_by", ""), turn.get("valid")
    hook = turn.get("webhook")

    if not ticket:
        klass, fig = "none", "NO TICKET"
        sub = ("Nothing was recorded, so this case cannot be audited and no "
               "person will ever see it. Every conversation is supposed to end "
               "in exactly one row -- including the dull ones.")
    elif not valid:
        klass, fig = "none", (who or "(blank)") + " ?"
        sub = ("Ticket " + escape(ticket) + " was written, but its Action By is "
               "not one of the two dropdown values. That cell will not filter "
               "and will not count, and no handoff was sent.")
    elif who == ACTED_BY_HUMAN:
        klass, fig = "human", "HUMAN"
        if turn.get("existing"):
            sub = ("Ticket " + escape(ticket) + " was ALREADY open for this "
                   "case, so no second row was written. One conversation is "
                   "one case, and the same case asked twice is still one "
                   "case. A person owns it and has not decided yet.")
        else:
            sub = ("Ticket " + escape(ticket) + ". Nobody has decided yet -- a "
                   "rule ran out, so the case is a person's. The customer "
                   "still got an answer; what changed is who owns the outcome.")
    else:
        klass, fig = "ai", "HANDLED BY AI"
        if turn.get("existing"):
            sub = ("Ticket " + escape(ticket) + " was ALREADY open for this "
                   "case, so no second row was written. A rule covered it and "
                   "the agent decided it.")
        else:
            sub = ("Ticket " + escape(ticket) + ". A rule in the rulebook "
                   "covered this case, so the agent decided it and said so on "
                   "the row. No person is needed and nothing was escalated.")

    rows = []
    if turn.get("existing"):
        if turn.get("unverified"):
            rows.append('<span class="venf ask">REQUESTED</span>The desk says '
                        + escape(turn["existing"]) + ' already exists, but no '
                        'Tickets row was read back in this run to confirm it. '
                        'That is a claim, not a record -- check the sheet '
                        'before believing it.')
        else:
            rows.append('<span class="venf">ENFORCED</span>No second row was '
                        'written, and this is not taken on trust: '
                        + escape(turn["existing"]) + ' was found in the '
                        'Tickets grid the specialist read back, so Action By '
                        'above is the sheet\'s own value.')
    if turn.get("handoff_skipped"):
        rows.append('<span class="venf">ENFORCED</span>Nothing was re-sent. '
                    'The case was already raised as '
                    + escape(turn["handoff_skipped"]) + ', and a handoff that '
                    'fires again every time the same customer asks again is '
                    'one nobody reads.')

    if ticket and valid and who == ACTED_BY_HUMAN and not turn.get("existing"):
        if hook and hook.get("ok"):
            rows.append('<span class="venf">ENFORCED</span>Python POSTed the '
                        'handoff to the escalation webhook -- HTTP '
                        + escape(str(hook.get("status"))) + '. Not the agent: '
                        'the model is never given a POST tool, so the '
                        'destination and the payload are both fixed in code.')
        elif hook:
            rows.append('<span class="venf">ENFORCED</span>Python tried to POST '
                        'the handoff and it failed -- '
                        + escape(str(hook.get("status"))) + '. The ticket row '
                        'is the record and it survives; the webhook is only '
                        'the notification. Chase it by hand.')
        else:
            rows.append('<span class="venf">ENFORCED</span>The handoff runs on '
                        '<code>if action_by == "Human"</code>, in Python. No '
                        'webhook is configured, so nobody was notified -- the '
                        'ticket still exists.')
    elif ticket and valid and not turn.get("existing"):
        rows.append('<span class="venf">ENFORCED</span>No handoff was sent, and '
                    'that is the same if-statement doing its job: the webhook '
                    'fires only when the column reads Human. One that fired on '
                    'every ticket is one nobody reads.')

    slack = turn.get("slack")
    if ticket and valid and who == ACTED_BY_HUMAN and slack:
        if slack.get("ok"):
            rows.append('<span class="venf">ENFORCED</span>The team channel was '
                        'told too: posted to Slack as the bot. Same '
                        'if-statement, second destination.')
        else:
            rows.append('<span class="venf">ENFORCED</span>Slack was NOT told -- '
                        + escape(str(slack.get("detail", ""))) +
                        ' The check ran; it is the delivery that failed, and '
                        'that is the difference between knowing and assuming.')

    if turn.get("chased") and turn.get("existing"):
        rows.append('<span class="venf">ENFORCED</span>Python noticed no row '
                    'had been written and asked once, explicitly. That ask is '
                    'what turned up the existing ticket -- the check earns its '
                    'keep even when the answer is "there already is one".')
    elif turn.get("chased") and ticket:
        rows.append('<span class="venf">ENFORCED</span>The Skill was told to '
                    'file a ticket and did not. Python noticed the missing row '
                    'and asked once, explicitly -- which is why there is a '
                    'ticket here at all.')
    elif turn.get("chased"):
        rows.append('<span class="venf">ENFORCED</span>Python noticed no ticket '
                    'had been written and asked for one, explicitly, on the '
                    'same session. It still did not file. That is the failure '
                    'rate of a Skill, caught in the act -- and it is why the '
                    'check exists rather than trusting the instruction.')
    elif ticket and not turn.get("existing"):
        rows.append('<span class="venf ask">REQUESTED</span>This ticket was '
                    'filed because a sentence in SKILL.md asked for one. That '
                    'is a request with a failure rate, not a guarantee -- turn '
                    'off "Guarantee a ticket every turn" in the sidebar to see '
                    'the raw rate.')
    elif not ticket:
        rows.append('<span class="venf ask">REQUESTED</span>SKILL.md asked for '
                    'a ticket and none was written, and nothing checked. Turn '
                    'on "Guarantee a ticket every turn" in the sidebar and '
                    'Python will ask again whenever this happens -- that is '
                    'the difference between a request and a guarantee.')

    body = "".join('<div class="vrow">' + r + '</div>' for r in rows)
    return ('<div class="verdict ' + klass + '"><span class="vk">who owns this '
            'case</span><div class="vfig">' + escape(fig) + '</div>'
            '<div class="vsub">' + sub + '</div>' + body + '</div>')


def bubble_html(turn) -> str:
    """One message. The customer's sits right and filled; the desk's sits left
    and outlined. Built as markup rather than st.chat_message because that
    widget draws every speaker on the same side, which is the one distinction
    a chat has to make."""
    if turn["role"] == "divider":
        return f'<div class="chat-div"><span>{escape(turn["text"])}</span></div>'

    body = escape(turn["text"]).replace(chr(10), "<br>")
    if turn["role"] == "user":
        return (f'<div class="chat-row me">'
                f'<div class="chat-msg">{body}</div>'
                f'<div class="chat-av">🧑</div></div>')

    err = (f'<div class="chat-err">the run failed: {escape(str(turn["error"]))}'
           f'</div>' if turn.get("error") else "")
    # A desk reply with no badge strip would look like a finished case even
    # when nothing was recorded, so every one of them carries it.
    meta = turn_meta_html(turn) if "ticket" in turn else ""
    return (f'<div class="chat-row desk"><div class="chat-av">🤝</div>'
            f'<div class="chat-msg">{body}{err}{meta}</div></div>')


# What each kind of step MEANS, in a sentence a reader can follow. The step
# titles themselves are internal ("says", "returns", "SHEET READ
# mcp__sheets__get_sheet_data") and belong in the stream on the right, not in
# the customer's half of the screen.
LIVE_PHRASES = {
    "deleg": "handing the case to a specialist",
    "read":  "reading the spreadsheet",
    "write": "writing the ticket row",
    "text":  "writing back",
    "sys":   "setting up",
    "done":  "wrapping up",
    "err":   "hit a problem",
}


def live_status(run):
    """(who, what) for the bubble, derived from the last step that arrived."""
    if not run or not run["steps"]:
        return "", ("starting the session -- the first call also starts the "
                    "sheets server, so the opening seconds are the slow ones")
    step = run["steps"][-1]
    what = LIVE_PHRASES.get(step["kind"], "working")
    if step["kind"] == "deleg":
        # The title carries the target, and which specialist was chosen is the
        # most interesting thing on screen at that moment.
        target = step["title"].split("->")[-1].strip()
        if target:
            what = f"handing the case to {target}"
    who = step.get("agent") or ""
    return ("" if who == "router" else who), what


def live_bubble_html(run) -> str:
    """The desk's bubble while it is still working -- same row, same side, so
    it settles into the finished reply instead of jumping."""
    who, what = live_status(run)
    speaker = f'<span class="who">{escape(who)}</span> &nbsp;·&nbsp; ' if who else ""
    if run:
        elapsed = time.time() - (run["started"] or time.time())
        counts = (f'{run["delegations"]} delegation(s) &nbsp;·&nbsp; '
                  f'{len(run["calls"])} tool call(s) &nbsp;·&nbsp; '
                  f'{run["reads"]} read &nbsp;·&nbsp; {run["writes"]} write'
                  f' &nbsp;·&nbsp; {elapsed:.0f}s')
    else:
        counts = "0 delegation(s) &nbsp;·&nbsp; 0 tool call(s) &nbsp;·&nbsp; 0s"
    return ('<div class="chat-row desk"><div class="chat-av">🤝</div>'
            '<div class="chat-msg live">'
            '<span class="dots"><i></i><i></i><i></i></span>'
            '<span class="lwork">Working…</span>'
            f'<div class="lstep">{speaker}{escape(what)}</div>'
            f'<div class="lcount">{counts}</div></div></div>')


def chat_html(chat, live_markup="") -> str:
    """The whole transcript as one block, repainted as a unit.

    One placeholder for the entire thread, rather than a widget per message:
    that is what lets the in-flight bubble be replaced by the finished reply
    without the messages above it being torn down and redrawn.
    """
    rows = "".join(bubble_html(t) for t in chat) + live_markup
    if not rows:
        rows = ('<div class="chat-empty">Nothing yet.<br>Write to the desk '
                'below, or send one of the preset cases.</div>')
    return f'<div class="chat-wrap">{rows}</div>'


def close_orphan_turn(chat) -> None:
    """Pair every customer message with a reply, even the abandoned ones.

    A turn runs inside the page pass that received it, so sending a second
    message while the first is still working makes Streamlit abandon that
    pass -- the reply is never appended and the transcript is left with a
    question nobody answered. That is worth SAYING, not hiding: an unanswered
    message is a case with no ticket, which is the one thing this app exists
    to make visible.
    """
    if chat and chat[-1]["role"] == "user":
        chat.append({
            "role": "assistant",
            "text": "*This turn was interrupted -- another message was sent "
                    "before it finished, so no reply and no ticket were "
                    "produced. Ask again.*",
            "ticket": "", "action_by": "", "valid": False, "chased": False,
            "delegations": 0, "cost": 0.0, "webhook": None, "slack": None,
            "error": None,
        })


def tiles_html(run) -> str:
    end = verdict(run)
    who, valid = action_by(run)
    ticket = run["row"][0] if run["row"] else ""

    if not who:
        who_val, who_tone, who_hint = "--", "t-mute", "no ticket row seen yet"
    elif not valid:
        who_val, who_tone = f"{who} !", "t-crit"
        who_hint = "not a dropdown value -- this cell will not filter"
    elif who == ACTED_BY_HUMAN:
        who_val, who_tone, who_hint = who, "t-warn", "a person owns this decision"
    else:
        who_val, who_tone, who_hint = who, "t-good", "a rule covered it"

    reason = (end.get("terminal_reason") or end.get("subtype") or "--") if end else \
             ("running" if run["started"] and not run["finished"] else "--")
    ok = reason in ("completed", "success")

    parts = [
        tile("Delegations", run["delegations"], "t-violet",
             "the router decides this at runtime"),
        tile("Tool calls", len(run["calls"]), "t-blue",
             f"{run['reads']} read · {run['writes']} write"),
        tile("Conversations", len(run["convos"]), "t-blue",
             "router + one per specialist"),
        tile("Turns", (end or {}).get("num_turns", "--") or "--", "",
             f"cap {st.session_state.get('max_turns', MAX_TURNS)}"),
        tile("Cost", f"${total_cost(run):.4f}", "t-orange",
             "as the SDK reports it"),
        tile("Ticket", ticket or "NONE", "t-aqua" if ticket else "t-crit",
             ("already on the sheet -- not written again"
              if run["ticket_existing"] else "one per conversation"),
             small=True),
        tile("Action by", who_val, who_tone, who_hint, small=True),
        tile("Sheets server", run["server"], "t-good"
             if run["server"] == "connected" else "t-warn",
             "proved by a call that came back", small=True),
        tile("Outcome", reason, "t-good" if ok else "t-crit",
             "anything but completed needs investigating", small=True),
    ]
    return f'<div class="gs-grid">{"".join(parts)}</div>'


def steps_html(run, tail=None) -> str:
    steps = run["steps"][-tail:] if tail else run["steps"]
    if not steps:
        return ('<div class="gs-stream"><div class="step"><div class="rail">'
                '<span class="dot"></span></div><div><div class="body">'
                'Nothing yet. Ask a question above.</div></div></div></div>')
    out = []
    for step in steps:
        chip = (f'<span class="chip {"router" if step["agent"] == "router" else "spec"}">'
                f'{escape(step["agent"])}</span>') if step["agent"] else ""
        body = (f'<div class="body {step["tone"]}">{escape(step["body"])}</div>'
                if step["body"] else "")
        mono = f'<span class="mono">{escape(step["mono"])}</span>' if step["mono"] else ""
        out.append(
            f'<div class="step {step["kind"]}"><div class="rail">'
            f'<span class="dot"></span></div><div><div class="head">{chip}'
            f'<span class="title">{escape(step["title"])}</span>'
            f'<span class="at">+{step["at"]:.1f}s</span></div>'
            f'{body}{mono}</div></div>')
    return f'<div class="gs-stream">{"".join(out)}</div>'


def table_html(headers, rows, numeric=()) -> str:
    head = "".join(f"<th>{escape(str(h))}</th>" for h in headers)
    body = []
    for row in rows:
        cells = []
        for i, cell in enumerate(row):
            klass = ' class="num"' if i in numeric else ""
            cells.append(f"<td{klass}>{cell if str(cell).startswith('<') else escape(str(cell))}</td>")
        body.append(f"<tr>{''.join(cells)}</tr>")
    return (f'<div class="gs-wrap"><table class="gs"><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def bar(value, peak) -> str:
    """A meter, not a chart: one measure against the largest in its column."""
    pct = 0 if not peak else max(2, round(100 * value / peak))
    return f'<div class="bar"><i style="width:{pct}%"></i></div>'


def card(title, body_html, note="") -> str:
    note_html = f'<p class="k">{escape(note)}</p>' if note else ""
    return f'<div class="gs-card"><h4>{escape(title)}</h4>{note_html}{body_html}</div>'


# ==========================================================================
# 5b. LOOKING AT THE SERVER
#     The one thing a screenshot cannot fake: what the MCP server says when
#     you ask it yourself, over the same transport the agent uses.
# ==========================================================================

# The nine tools on this server that only READ. Everything else changes
# something -- a cell, a tab, a whole spreadsheet, or who can see it.
SHEETS_READ_TOOLS = (
    "get_sheet_data", "get_sheet_formulas", "list_sheets",
    "get_multiple_sheet_data", "get_multiple_spreadsheet_summary",
    "list_spreadsheets", "list_folders", "search_spreadsheets",
    "find_in_spreadsheet",
)

# The ones worth naming out loud when you look at "mcp__sheets__*".
SHEETS_ALARMING = ("share_spreadsheet", "rename_sheet", "create_spreadsheet",
                   "batch_update", "add_columns", "copy_sheet", "add_chart")


def agent_may_call(tool_name: str, agent_name: str) -> bool:
    """Would this agent be ALLOWED to call this server tool?

    allowed_tools is a global approval list and it holds "mcp__sheets__*", so
    the answer starts at yes for everything. The only thing that takes a tool
    away is the agent's own disallowedTools. Skills do not appear here at all
    -- which is the point of the table this feeds.
    """
    full = f"mcp__sheets__{tool_name}"
    if agent_name == "router":
        return True
    blocked = SUBAGENTS[agent_name].disallowedTools or []
    return full not in blocked


@st.cache_data(show_spinner=False, ttl=900)
def probe_sheets_server(timeout: float = 150.0) -> dict:
    """Speak MCP to the sheets server by hand, with no agent in the way.

    The SDK does this handshake for you on every run. Doing it here, over the
    same stdio transport, is the only way to see WHAT WAS OFFERED rather than
    what got used -- and the gap between those two is the whole lesson.

    stdio, not http: the server is a subprocess this machine launches, and the
    wire format is newline-delimited JSON-RPC over its stdin and stdout.
    """
    out = {"ok": False, "error": "", "server": {}, "protocol": "",
           "capabilities": {}, "tools": [], "resources": None,
           "prompts": None, "elapsed": 0.0, "stderr": "", "raw": []}
    if not SERVICE_ACCOUNT_PATH:
        out["error"] = "SERVICE_ACCOUNT_PATH is not set"
        return out

    started = time.time()
    env = dict(os.environ)
    env["SERVICE_ACCOUNT_PATH"] = SERVICE_ACCOUNT_PATH
    server = MCP_SERVERS["sheets"]
    proc, errors = None, []
    try:
        proc = subprocess.Popen(
            [server["command"], *server["args"]],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=env, cwd=HERE, text=True,
            encoding="utf-8", errors="replace", bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

        inbox = queue.Queue()

        # readline(), not `for line in proc.stdout`: iterating a pipe in text
        # mode reads ahead, and the read-ahead never fills because the server
        # is waiting for OUR next request. That deadlocks with both sides
        # politely waiting for the other.
        def reader():
            try:
                for line in iter(proc.stdout.readline, ""):
                    inbox.put(line)
            except Exception:
                pass
            inbox.put(None)

        # stderr gets its own drain from the start. uvx narrates its package
        # resolution down this pipe, and an undrained pipe that fills up stops
        # the server dead -- with no error, because nothing has failed.
        def drain_errors():
            try:
                for line in iter(proc.stderr.readline, ""):
                    errors.append(line)
                    if len(errors) > 400:
                        del errors[:200]
            except Exception:
                pass

        threading.Thread(target=reader, daemon=True).start()
        threading.Thread(target=drain_errors, daemon=True).start()
        deadline = started + timeout

        def send(payload):
            out["raw"].append({"->": payload})
            proc.stdin.write(json.dumps(payload) + "\n")
            proc.stdin.flush()

        def recv():
            while time.time() < deadline:
                try:
                    line = inbox.get(timeout=0.5)
                except queue.Empty:
                    continue
                if line is None:
                    raise RuntimeError("the server closed its output")
                if not line.strip():
                    continue
                message = json.loads(line)
                out["raw"].append({"<-": message})
                return message
            raise TimeoutError(f"no reply within {timeout:.0f}s")

        # 1. initialize -- agree a protocol version, swap capabilities
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                         "clientInfo": {"name": "d20-control-room",
                                        "version": APP_VERSION}}})
        init = recv().get("result", {})
        out["server"] = init.get("serverInfo", {})
        out["protocol"] = init.get("protocolVersion", "")
        out["capabilities"] = init.get("capabilities", {})
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})

        # 2. discovery -- all three primitives, because a server implements
        #    only the ones it needs and you should ask rather than assume
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        out["tools"] = recv().get("result", {}).get("tools", [])
        send({"jsonrpc": "2.0", "id": 3, "method": "resources/list", "params": {}})
        answer = recv()
        out["resources"] = (None if "error" in answer
                            else answer.get("result", {}).get("resources", []))
        send({"jsonrpc": "2.0", "id": 4, "method": "prompts/list", "params": {}})
        answer = recv()
        out["prompts"] = (None if "error" in answer
                          else answer.get("result", {}).get("prompts", []))
        out["ok"] = True
    except Exception as exc:                        # noqa: BLE001 -- shown in UI
        out["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if proc:
            # kill, and do NOT read the pipes afterwards. uvx launches the
            # real server as a CHILD, so the grandchild can outlive a
            # terminate() still holding the pipe open -- and a blocking
            # .read() on it then never returns. Everything worth keeping was
            # already drained by the threads above.
            try:
                proc.kill()
            except Exception:
                pass
            out["stderr"] = "".join(errors)[-2000:]
    out["elapsed"] = time.time() - started
    return out

# ==========================================================================
# 6. THE PAGE
# ==========================================================================

st.set_page_config(page_title=APP_TITLE, page_icon="🤝", layout="wide",
                   initial_sidebar_state="expanded")

state = st.session_state
state.setdefault("run", blank_run())
state.setdefault("history", [])          # every completed run this session
state.setdefault("session_id", None)     # ties every Send to ONE agent session
state.setdefault("questions", [])
state.setdefault("chat", [])             # the visible transcript, one dict a turn
state.setdefault("max_turns", MAX_TURNS)
state.setdefault("max_output", MAX_OUTPUT_TOKENS)

# ---------- sidebar ----------
with st.sidebar:
    st.markdown(f"### {APP_AUTHOR}")
    st.caption(f"{APP_TITLE} · v{APP_VERSION}")
    st.caption(APP_KICKER)

    st.divider()
    st.caption("RUN SETTINGS")
    state["max_turns"] = st.slider("max_turns", 5, 60, state["max_turns"],
                                   help="Every delegation is a whole nested "
                                        "conversation with its own turns.")
    state["max_output"] = st.select_slider(
        "CLAUDE_CODE_MAX_OUTPUT_TOKENS", [512, 1024, 2024, 4096],
        value=state["max_output"],
        help="There is no max_tokens on ClaudeAgentOptions -- it goes in env.")
    state["guarantee_ticket"] = st.toggle(
        "Guarantee a ticket every turn", value=state.get("guarantee_ticket", True),
        help="The Skill ORDERS one ticket per case, and a Skill is a request "
             "with a failure rate. ON: if a turn ends with no row written, "
             "Python asks the desk once, explicitly, on the same session. OFF: "
             "you see the raw compliance rate instead.")
    keep_session = st.toggle("Continue the same conversation", value=True,
                             help="ON: the second question resumes the first "
                                  "session, so the agent still knows the order "
                                  "and that it already filed a ticket. OFF: "
                                  "every question is a new case and a new ticket.")

    st.divider()
    st.caption("RULEBOOK")
    if RULEBOOK_ERROR:
        st.error("refund_rulebook.txt is unreadable, so the agent has no "
                 "refund policy at all. Running now would not give you a "
                 "broken run you would notice -- it would give you a "
                 "confident agent inventing percentages.")
    else:
        _intro, _rules = rulebook_sections(RULEBOOK)
        st.caption(_intro)
        for _title, _body in _rules:
            # The bracketed half of a heading is a whole line on its own in a
            # sidebar this narrow, so the label keeps the name and the body
            # keeps everything.
            with st.expander(_title.split("(")[0].strip()):
                st.code(_body, language="text")
        st.caption("Policy as DATA, not code: this is `refund_rulebook.txt`, "
                   "read at startup and pasted into the router's prompt "
                   "verbatim. There is no percentage and no day count anywhere "
                   "in the Python or in any SKILL.md -- edit the file, re-run, "
                   "no redeploy.")

    st.divider()
    st.caption("ENVIRONMENT")
    checks = [
        ("ANTHROPIC_API_KEY", bool(os.getenv("ANTHROPIC_API_KEY"))),
        ("GOOGLE_SHEET_ID", bool(SHEET_ID)),
        ("SERVICE_ACCOUNT_PATH",
         bool(SERVICE_ACCOUNT_PATH) and os.path.isfile(SERVICE_ACCOUNT_PATH or "")),
        ("ESCALATION_WEBHOOK_URL", bool(WEBHOOK_URL)),
        ("SLACK_BOT_TOKEN", bool(SLACK_BOT_TOKEN)),
        ("SLACK_CHANNEL_ID", bool(SLACK_CHANNEL_ID)),
        ("refund_rulebook.txt", not RULEBOOK_ERROR),
    ]
    for name, ok in checks:
        st.markdown(f"{'✅' if ok else '⚠️'} `{name}`")
    st.caption("Both handoffs are optional -- without them the ticket is still "
               "written, nobody is notified, and the app says so rather than "
               "reporting a success it did not have.")

    st.divider()
    if st.button("Clear conversation", width="stretch", key="clear_side"):
        # Clear is what starts a NEW conversation, and therefore a new ticket.
        clear_case()
        st.rerun()
    if state["session_id"]:
        st.caption(f"session `{state['session_id'][:8]}…` · "
                   f"{len(state['questions'])} question(s) in it")

paint()

run = state["run"]
# Nothing is "pending" between reruns any more: a turn is run in the Run tab,
# in the same pass that received it. Kept as a name because the sidebar and the
# MCP probe still read it, and because a future long-running mode would want it.
busy = False

st.markdown(
    f'<div class="gs-mast">'
    f'<span class="kicker">{escape(APP_KICKER)}</span>'
    f'<span class="rule"></span>'
    f'<h1>{escape(APP_TITLE_LEAD)}<em>{escape(APP_TITLE_TAIL)}</em></h1>'
    f'<span class="sub">{escape(APP_STORY)}</span>'
    f'<span class="sig">one router · three specialists · one MCP server · '
    f'one spreadsheet &nbsp;·&nbsp; {escape(APP_AUTHOR)} '
    f'&lt;{escape(APP_CONTACT)}&gt; &nbsp;·&nbsp; v{APP_VERSION} · built '
    f'{APP_BUILT} · model <code>{escape(MODEL)}</code> · today {TODAY}'
    f'</span></div>', unsafe_allow_html=True)

if RULEBOOK_ERROR:
    st.error(f"refund_rulebook.txt is missing or unreadable: {RULEBOOK_ERROR}. "
             "Running now would not give you a broken run you would notice -- "
             "it would give you a confident agent inventing refund percentages. "
             "Fix the file first.")

TAB_NAMES = ["▶  Run", "Flow", "Tool calls", "MCP live", "Agents & Skills",
             "The sheet", "Cost & tokens", "Ticket & handoff", "Raw JSON",
             "How it works"]
tabs = st.tabs(TAB_NAMES)

# ---------------------------------------------------------------- RUN ----
# Two columns, and the split is the point. On the left the desk is a plain
# chatbot -- the only thing a customer would ever see. On the right is
# everything that produced it, live. Neither is a summary of the other: the
# right-hand column is read off the SDK's own message stream.
with tabs[0]:
    st.markdown("#### The support desk")
    st.caption("One chat is ONE case. Every message resumes the same agent "
               "session, so the desk still knows which order you meant and "
               "that it already filed a ticket -- a follow-up updates that row "
               "instead of opening a second. Clear, in the sidebar, is what "
               "starts a new case and a new ticket.")

    talk, glass = st.columns([6, 5], gap="large")

    with talk:
        st.markdown("##### Conversation")
        st.caption("All the customer ever sees. Their messages sit right, the "
                   "desk's sit left.")
        # Filled at the END of the pass, so during a run it is not still
        # asserting the previous case's verdict.
        verdict_slot = st.empty()
        # A message that was abandoned mid-run left a question with no answer.
        # Close it before drawing, so every bubble on the right has one facing
        # it on the left.
        close_orphan_turn(state["chat"])
        # ONE placeholder for the whole thread: the in-flight bubble is
        # replaced by the finished reply without redrawing what is above it.
        transcript = st.empty()
        transcript.markdown(chat_html(state["chat"]), unsafe_allow_html=True)

        typed = st.chat_input("Write to the support desk...", key="desk_in",
                              disabled=bool(RULEBOOK_ERROR))

        note_col, clear_col = st.columns([3, 1], vertical_alignment="center")
        with note_col:
            if state["session_id"]:
                st.caption(f"Continuing one session "
                           f"`{state['session_id'][:8]}…` · "
                           f"{len(state['questions'])} message(s) in this case.")
            else:
                st.caption("No session yet -- the next message opens a new "
                           "case, and a new ticket.")
        with clear_col:
            # A second Clear, where the conversation is. It has to do exactly
            # what the sidebar one does: a new transcript is only honest if it
            # is also a new session, or the agent would resume the old case and
            # update a ticket that is no longer on screen.
            if st.button("Clear", width="stretch", key="clear_chat",
                         disabled=not state["chat"],
                         help="End this case and start a new conversation -- "
                              "new session, and the next ticket is a new row."):
                clear_case()
                st.rerun()

        preset_sent = None
        with st.expander("Preset cases -- each one lands on a different branch"):
            st.caption("Every dated order in the sheet is well outside the "
                       "7-day window, so every refund case here escalates. To "
                       "watch the flip, leave the Status on Delivered and set "
                       "one order's date to within 7 days of today, then ask "
                       "again -- one cell, no code. An Electronics order inside "
                       "the window pays 50%, Apparel 100%, and Perishable "
                       "escalates at 0% because refusing money is as "
                       "consequential as paying it. Nothing in the sheet reads "
                       "'Delayed' either, so the delay-analyst will not be "
                       "called until one does.")
            for i, (label, message) in enumerate(PRESETS):
                row_l, row_r = st.columns([5, 1], vertical_alignment="center")
                row_l.markdown(f"**{label}**")
                row_l.caption(message)
                if row_r.button("Send", key=f"preset_{i}", width="stretch",
                                disabled=bool(RULEBOOK_ERROR)):
                    preset_sent = message

    with glass:
        st.markdown("##### Behind the scenes")
        st.caption("Read straight off the SDK's message stream while it runs. "
                   "Nothing here is simulated and nothing is priced by hand.")
        tiles_slot = st.empty()
        live_slot = st.empty()
        hero_slot = st.empty()
        st.markdown("**Step by step** -- every message the SDK produced, in order")
        stream_slot = st.empty()

    # ---- the turn itself, in THIS pass -------------------------------------
    asked = (typed or "").strip() or preset_sent
    if asked:
        if not keep_session:
            # A fresh session is a fresh case, and therefore a fresh ticket.
            # Say so in the transcript rather than letting the ticket ID jump.
            state["session_id"] = None
            state["questions"] = []
            state["chat"].append({"role": "divider",
                                  "text": "new case · fresh session · fresh ticket"})

        state["chat"].append({"role": "user", "text": asked})
        state["questions"].append(asked)

        def repaint(live_markup=""):
            transcript.markdown(chat_html(state["chat"], live_markup),
                                unsafe_allow_html=True)

        verdict_slot.markdown(case_banner_working_html(),
                              unsafe_allow_html=True)
        repaint(live_bubble_html(None))
        run, desk_turn = state["run"], None
        try:
            run = execute_turn(asked,
                               state["session_id"] if keep_session else None,
                               repaint, tiles_slot, live_slot, stream_slot)
            state["run"] = run
            state["history"].append(run)
            who, valid = action_by(run)
            desk_turn = {
                "role": "assistant",
                "text": run["reply"] or "*The desk returned no reply.*",
                "ticket": run["row"][0] if run["row"] else "",
                "action_by": who,
                "valid": valid,
                "chased": run["ticket_chased"],
                "existing": run["ticket_existing"],
                "unverified": run["ticket_unverified"],
                "handoff_skipped": run["handoff_skipped"],
                "delegations": run["delegations"],
                "cost": total_cost(run),
                "webhook": run["webhook"],
                "slack": run["slack"],
                "error": run["error"],
            }
        finally:
            # Whatever happened, the thread does not get left showing a bubble
            # that is still thinking. An unanswered message is the thing this
            # app is least allowed to hide.
            if desk_turn is None:
                close_orphan_turn(state["chat"])
            else:
                state["chat"].append(desk_turn)
            repaint()

    verdict_slot.markdown(case_banner_html(last_verdict_turn(state["chat"])),
                          unsafe_allow_html=True)

    # ---- the right-hand column, once nothing is in flight -------------------
    if not asked:
        run = state["run"]
        tiles_slot.markdown(tiles_html(run), unsafe_allow_html=True)
        stream_slot.markdown(steps_html(run), unsafe_allow_html=True)

    who, valid = action_by(state["run"])
    if state["run"]["reply"] or state["run"]["row"]:
        klass = ("ai" if who == ACTED_BY_AI else
                 "human" if who == ACTED_BY_HUMAN else "bad" if who else "")
        hero_slot.markdown(
            f'<div class="gs-hero"><span class="lab">Who owned this decision'
            f'</span><div class="fig {klass}">{escape(who or "no ticket")}</div>'
            f'<div class="note"><b>The customer heard:</b> '
            f'{escape(state["run"]["reply"] or "-- nothing --")}</div></div>',
            unsafe_allow_html=True)

# --------------------------------------------------------------- FLOW ----
with tabs[1]:
    st.markdown("#### The shape of the system, with this run's traffic on it")
    st.caption("The boxes are fixed. The numbers are what actually happened -- "
               "a workflow would call all three every time; the router decides "
               "at runtime, and 0 is a legitimate answer for two of them.")

    def node(css_class, name, detail, hits=None):
        badge = (f'<span class="hits">{hits} call(s)</span>'
                 if hits is not None else "")
        return (f'<div class="node {css_class}">{badge}<div class="n">'
                f'{escape(name)}</div><div class="d">{escape(detail)}</div></div>')

    fan = "".join([
        node("reader", "order-lookup",
             "Skill: order-lookup · reads the Order tab · cannot write, cannot "
             "delegate onward · returns status, carrier, ETA, category, date, "
             "email, name", run["hits"]["order-lookup"]),
        node("reader", "delay-analyst",
             "Skill: delay-analysis · reads the Delays tab · only called when "
             "the status is a delay · returns the reason as written, or "
             "no_reason_logged", run["hits"]["delay-analyst"]),
        node("writer", "ticket-writer",
             "Skill: ticket-writer · the ONLY agent that writes · appends one "
             "row to Tickets · returns ticket_id, action_by",
             run["hits"]["ticket-writer"]),
    ])
    st.markdown(
        f'<div class="flow">'
        f'{node("", "1 · the customer", "one message, in their own words: "
               + short(run["question"] or "nothing asked yet", 160))}'
        f'<div class="arrow">▼ prompt</div>'
        f'{node("router", "2 · the router (this process)",
                "Skill: support-router · system prompt carries today\'s date and "
                "the refund rulebook verbatim · holds the sheets tools and is "
                "told not to use them · decides who to call")}'
        f'<div class="arrow">▼ the Agent tool -- one call per specialist, '
        f'{run["delegations"]} this run</div>'
        f'<div class="fan">{fan}</div>'
        f'<div class="arrow">▼ every one of them talks to the same server</div>'
        f'{node("", "3 · MCP server: mcp-google-sheets (uvx subprocess)",
                "Holds SERVICE_ACCOUNT_PATH. No agent ever sees the key. "
                f"{run['reads']} read call(s), {run['writes']} write call(s) "
                "this run.")}'
        f'<div class="arrow">▼</div>'
        f'{node("", "4 · the spreadsheet", "Order · Delays · Tickets  --  "
                + (SHEET_ID or "GOOGLE_SHEET_ID is not set"))}'
        f'<div class="arrow">▼ only when Action By = Human</div>'
        f'{node("human", "5 · the handoff (Python, not an agent)",
                "post_escalation() POSTs the ticket to ESCALATION_WEBHOOK_URL. "
                "Fixed destination, fixed payload -- the model has no POST tool.")}'
        f'</div>', unsafe_allow_html=True)

    st.markdown("#### What happened this time")
    if not run["steps"]:
        st.info("Run a question and the real sequence appears here.")
    else:
        order = [c for c in run["calls"] if c["kind"] == "delegate"]
        rows = []
        for i, call in enumerate(order, 1):
            target = call["input"].get("subagent_type", "?")
            rows.append([i, target, f"+{call['at']:.1f}s",
                         f"{call['ms'] or 0:,} ms",
                         short(str(call["input"].get("prompt", "")), 180)])
        if rows:
            st.markdown(table_html(
                ["#", "Specialist", "Called at", "Took", "Context handed down"],
                rows, numeric={0, 3}), unsafe_allow_html=True)
        else:
            st.markdown(card("0 delegations",
                             "<p>The router answered without calling anyone. "
                             "That is a real outcome -- it happens when the "
                             "customer gives no order ID -- but here it still "
                             "has to file a ticket, so a run with 0 delegations "
                             "and no ticket row means something went wrong.</p>"),
                        unsafe_allow_html=True)

# ---------------------------------------------------------- TOOL CALLS ----
with tabs[2]:
    st.markdown("#### Every tool call this run made")
    counts = {
        "delegate": run["delegations"],
        "read": sum(1 for c in run["calls"] if c["kind"] == "read"),
        "write": run["writes"],
        "skill": sum(1 for c in run["calls"] if c["kind"] == "skill"),
        "internal": sum(1 for c in run["calls"] if c["kind"] == "internal"),
    }
    st.markdown(
        '<div class="gs-grid">'
        + tile("Total tool calls", len(run["calls"]), "t-blue",
               "the number people mean by 'how many tool calls'")
        + tile("Agent / Task", counts["delegate"], "t-violet", "delegations")
        + tile("Sheet reads", counts["read"], "t-aqua", "get_sheet_data & friends")
        + tile("Sheet writes", counts["write"], "t-crit", "update_cells only")
        + tile("Skill loads", counts["skill"], "", "SKILL.md pulled in")
        + tile("SDK internal", counts["internal"], "t-mute", "everything else")
        + "</div>", unsafe_allow_html=True)

    st.caption("A write looks exactly like a read in the stream. Only the tool "
               "NAME and WHO called it tell them apart -- which is why the kind "
               "column exists and why the write rows are the ones to read.")

    if not run["calls"]:
        st.info("No tool calls yet.")
    else:
        rows = []
        for call in run["calls"]:
            state_chip = ('<span class="chip bad">error</span>' if call["is_error"]
                          else '<span class="chip ok">ok</span>' if call["is_error"] is False
                          else '<span class="chip sdk">open</span>')
            kind_chip = (f'<span class="chip '
                         f'{KIND_STYLE[call["kind"]][1]}">{call["kind"]}</span>')
            rows.append([
                call["n"],
                f'<span class="chip {"router" if call["agent"] == "router" else "spec"}">'
                f'{escape(call["agent"])}</span>',
                escape(call["name"]), kind_chip,
                f"+{call['at']:.1f}s",
                f"{call['ms']:,}" if call["ms"] is not None else "--",
                state_chip,
                escape(short(str(call["result"] or ""), 120)),
            ])
        st.markdown(table_html(
            ["#", "Called by", "Tool", "Kind", "At", "ms", "Result", "Returned"],
            rows, numeric={0, 5}), unsafe_allow_html=True)

        st.markdown("#### Arguments and results, call by call")
        st.caption("The arguments are the model's own -- nothing in the code "
                   "names a sheets tool or fills in a range.")
        for call in run["calls"]:
            head = (f"#{call['n']}  {call['agent']}  ·  {call['name']}  "
                    f"({call['kind']})")
            with st.expander(head, expanded=call["kind"] == "write"):
                st.markdown("**input**")
                st.json(call["input"], expanded=False)
                st.markdown("**result**")
                result = call["result"]
                if result is None:
                    st.caption("no result block was paired to this call")
                else:
                    try:
                        st.json(json.loads(result), expanded=False)
                    except (ValueError, TypeError):
                        st.code(result[:4000], language="text")

# ----------------------------------------------------------- MCP LIVE ----
with tabs[3]:
    st.markdown("#### Ask the server yourself, with no agent in the way")
    st.caption("The SDK runs this exact handshake on every question. Running "
               "it here shows what was OFFERED rather than what got used -- "
               "and the gap between those two is the whole point of the tab.")

    if st.button("Probe the sheets server", type="primary", key="probe_btn",
                 disabled=busy):
        with st.spinner("uvx is launching mcp-google-sheets and answering "
                        "four JSON-RPC calls..."):
            probe_sheets_server.clear()
            state["probe"] = probe_sheets_server()

    probe = state.get("probe")
    if not probe:
        st.info("Press the button. It launches the same subprocess the agent "
                "uses, speaks JSON-RPC to it over stdin and stdout, and shuts "
                "it down again. Nothing is written and no tokens are spent.")
    elif not probe["ok"]:
        st.error(f"Could not talk to the server: {probe['error']}")
        if probe["stderr"]:
            st.code(probe["stderr"], language="text")
    else:
        tools = probe["tools"]
        names = [t["name"] for t in tools]
        reads = [n for n in names if n in SHEETS_READ_TOOLS]
        mutates = [n for n in names if n not in SHEETS_READ_TOOLS]
        st.markdown(
            '<div class="gs-grid">'
            + tile("Tools offered", len(tools), "t-blue",
                   "discovered on connect, not listed in any file")
            + tile("Read-only", len(reads), "t-aqua", "safe to hand out")
            + tile("Tools that CHANGE things", len(mutates), "t-crit",
                   "cells, tabs, whole spreadsheets, sharing")
            + tile("Approved by our config", len(tools), "t-crit",
                   "mcp__sheets__* is every one of them")
            + tile("Handshake", f"{probe['elapsed']:.1f}s", "",
                   "including the uvx cold start", small=True)
            + tile("Transport", "stdio", "t-violet",
                   "a local subprocess, not a URL", small=True)
            + "</div>", unsafe_allow_html=True)

        st.markdown(
            f"Server **{escape(str(probe['server'].get('name', '?')))}** "
            f"v{escape(str(probe['server'].get('version', '?')))} · protocol "
            f"`{escape(probe['protocol'])}`")

        st.markdown("#### Who may call what")
        st.caption("allowed_tools holds one wildcard, so every row starts at "
                   "yes. The only thing that takes a tool away is that agent's "
                   "own disallowedTools. Nothing a Skill says appears in this "
                   "table -- a Skill is a request, and this is the enforcement.")
        rows = []
        for tool in tools:
            name = tool["name"]
            kind = ("read" if name in SHEETS_READ_TOOLS else "write")
            cells = [f'<span class="chip {kind}">{escape(name)}</span>']
            for who in ("router", "order-lookup", "delay-analyst", "ticket-writer"):
                ok = agent_may_call(name, who)
                risky = ok and name not in SHEETS_READ_TOOLS and who != "ticket-writer"
                cells.append('<span class="chip bad">yes</span>' if risky
                             else ('<span class="chip ok">yes</span>' if ok
                                   else '<span class="chip sdk">blocked</span>'))
            rows.append(cells)
        st.markdown(table_html(
            ["Server tool", "router", "order-lookup", "delay-analyst",
             "ticket-writer"], rows), unsafe_allow_html=True)
        st.error(
            f"Read the red cells. {len(mutates)} of the {len(tools)} tools on "
            f"this server change something, and `mcp__sheets__*` approves all "
            f"of them for the router and for both read-only specialists. Their "
            f"disallowedTools removes exactly two -- update_cells and "
            f"batch_update_cells -- so "
            f"`{'`, `'.join(t for t in SHEETS_ALARMING if t in names)}` are "
            f"still approved for agents whose entire job is to read one tab. "
            f"Nothing in code stops them. Only sentences in their Skills do.")
        st.caption("The fix is not a longer Skill. It is naming the read tools "
                   "instead of the wildcard -- and even that cannot say "
                   "'update_cells for the ticket-writer only', because "
                   "allowed_tools is global. A per-agent guarantee needs a "
                   "different shape: a separate session for the writer, or a "
                   "custom MCP tool that can only append to Tickets.")

        st.markdown("#### The three MCP primitives, as THIS server answers them")
        one, two, three = st.columns(3)
        one.metric("tools/list", len(tools))
        two.metric("resources/list",
                   "not implemented" if probe["resources"] is None
                   else len(probe["resources"]))
        three.metric("prompts/list",
                     "not implemented" if probe["prompts"] is None
                     else len(probe["prompts"]))
        st.markdown(
            "- **Tools** are *model*-controlled: things the agent can DO. It "
            "picks one from the description.\n"
            "- **Resources** are *application*-controlled: things to READ, "
            "addressed by URI. This server declares the capability and "
            "exposes none -- you reach cells through tools instead.\n"
            "- **Prompts** are *user*-controlled: templates a person picks, "
            "surfaced as slash commands. Declared here, and empty.\n\n"
            "A server implements only what it needs. Ask it rather than "
            "assuming: that is what discovery is for.")
        with st.expander("what the server declared in its capabilities"):
            st.json(probe["capabilities"], expanded=True)

        st.markdown("#### The schema the agent reads to choose a tool")
        default = names.index("get_sheet_data") if "get_sheet_data" in names else 0
        pick = st.selectbox("Inspect any tool the server offers", names,
                            index=default, key="probe_pick")
        st.json(next(t for t in tools if t["name"] == pick), expanded=False)
        st.caption("The **description** is prompt text -- it is how a "
                   "specialist decides to call this rather than one of the "
                   "other nineteen. The **inputSchema** is what its arguments "
                   "are checked against. Nobody in this project wrote either.")

        with st.expander("the raw JSON-RPC, both directions"):
            st.caption("MCP is JSON-RPC over stdin and stdout. That is the "
                       "entire wire format.")
            st.code(json.dumps(probe["raw"], indent=2)[:60000], language="json")
        if probe["stderr"]:
            with st.expander("the server's stderr"):
                st.code(probe["stderr"], language="text")

# ----------------------------------------------------- AGENTS & SKILLS ----
with tabs[4]:
    st.markdown("#### The team, read off the live AgentDefinition objects")
    st.caption("Nothing here is typed out by hand. Change SUBAGENTS above and "
               "this panel changes with it -- a panel that can disagree with "
               "the config is worse than no panel.")

    cards = []
    for name, agent in SUBAGENTS.items():
        writes = not any("update_cells" in t for t in (agent.disallowedTools or []))
        role = ("WRITES the Tickets tab" if writes else "READ ONLY")
        chip = "write" if writes else "read"
        cards.append(
            f'<div class="gs-card"><h4>{escape(name)} '
            f'<span class="chip {chip}">{role}</span></h4>'
            f'<p><b>description</b> -- what the ROUTER reads when it picks:<br>'
            f'{escape(agent.description)}</p>'
            f'<p><b>prompt</b> -- all the context it will ever have:<br>'
            f'{escape(agent.prompt)}</p>'
            f'<p class="k">skills {agent.skills} · mcpServers {agent.mcpServers} '
            f'· model {agent.model}</p>'
            f'<p class="k">disallowedTools {agent.disallowedTools}</p></div>')
    st.markdown(f'<div class="gs-three">{"".join(cards)}</div>',
                unsafe_allow_html=True)

    st.markdown("#### The router")
    left, right = st.columns([1, 1], gap="large")
    with left:
        st.markdown(card(
            "allowed_tools -- ONE GLOBAL approval list",
            "<p>" + "<br>".join(f"<code>{escape(t)}</code>" for t in ALLOWED_TOOLS)
            + "</p><p><b>Read that second line again.</b> "
            "<code>mcp__sheets__*</code> approves the write tools for EVERY "
            "agent in the session, the router included. What actually keeps "
            "the readers out of the Tickets tab is their own "
            "<code>disallowedTools</code>, and what keeps the router out of "
            "the sheet entirely is one sentence in a Skill. A Skill is a "
            "REQUEST with a non-zero failure rate; disallowedTools is not. "
            "Try it: ask \"mark order 1004 as shipped\" and watch which agent "
            "obliges.</p>"), unsafe_allow_html=True)
        st.markdown(card(
            "permission_mode = dontAsk",
            "<p>Nothing pauses for approval. That is a deliberate choice, not "
            "a shortcut: escalation here is RECORDED, not enforced. The ticket "
            "says who owns the decision and a person works the queue "
            "afterwards.</p>"), unsafe_allow_html=True)
    with right:
        st.markdown(card(
            "Three things in the system prompt, and why each is there",
            "<p><b>the role</b> -- one sentence, because the routing lives in "
            "the Skill.<br><b>today's date</b> -- a fact the model cannot look "
            "up and must not guess. A model has no clock.<br><b>the rulebook</b>"
            " -- policy owned by someone else, pasted in verbatim.</p>"
            "<p>SKILL.md says HOW TO BEHAVE. The rulebook says WHAT THE POLICY "
            "IS. Keeping them apart means the person who owns refund policy "
            "never opens a Skill file.</p>"), unsafe_allow_html=True)

    with st.expander("system_prompt -- exactly what the router was handed"):
        st.code(ROUTER_PROMPT, language="text")
    with st.expander("refund_rulebook.txt -- policy as DATA, not code"):
        st.caption(f"{RULEBOOK_PATH} · edit this file and re-run: no Python "
                   f"change, no Skill change, no redeploy. There is no refund "
                   f"percentage anywhere else in this project.")
        st.code(RULEBOOK or RULEBOOK_ERROR, language="text")

    st.markdown("#### The four Skills on disk")
    for skill in OUR_SKILLS:
        path = os.path.join(HERE, ".claude", "skills", skill, "SKILL.md")
        with st.expander(f"{skill}/SKILL.md"):
            try:
                with open(path, encoding="utf-8") as fh:
                    st.code(fh.read(), language="markdown")
            except OSError as exc:
                st.error(f"missing: {exc}")

# ---------------------------------------------------------- THE SHEET ----
with tabs[5]:
    st.markdown("#### The database is a Google spreadsheet")
    st.caption("Three tabs, one service account, one MCP server. The agents "
               "never hold a credential -- the key is an env var on the SERVER "
               "subprocess, and no prompt can leak what no agent can see.")
    st.markdown(
        '<div class="gs-grid">'
        + tile("Spreadsheet ID", SHEET_ID or "not set",
               "t-blue" if SHEET_ID else "t-crit", "GOOGLE_SHEET_ID in .env",
               small=True)
        + tile("Tabs", len(SHEET_SCHEMA), "", "Order · Delays · Tickets")
        + tile("MCP server", "mcp-google-sheets", "t-aqua",
               "launched with uvx, on demand", small=True)
        + tile("Server status", run["server"],
               "t-good" if run["server"] == "connected" else "t-warn",
               "proved by a call that came back", small=True)
        + tile("Access needed", "EDITOR", "t-warn",
               "the earlier days only read; this one writes", small=True)
        + "</div>", unsafe_allow_html=True)
    if SHEET_URL:
        st.markdown(f"[Open the spreadsheet]({SHEET_URL})")

    st.markdown("#### The schema, and who is allowed to touch it")
    for tab_name, spec in SHEET_SCHEMA.items():
        chip = "write" if spec["access"] == "WRITE" else "read"
        cols = "".join(f'<span class="chip">{escape(c)}</span> '
                       for c in spec["columns"])
        st.markdown(
            f'<div class="gs-card"><h4>{escape(tab_name)} '
            f'<span class="chip {chip}">{spec["access"]}</span> '
            f'<span class="chip spec">{escape(spec["owner"])}</span></h4>'
            f'<p>{cols}</p><p class="k">{escape(spec["note"])}</p></div>',
            unsafe_allow_html=True)

    st.markdown("#### What the specialists actually read back this run")
    st.caption("Not a second read of our own -- the exact rows that came out "
               "of the tool results, which is the only version the agent ever "
               "saw. If the answer looks wrong, it is either here or it was "
               "invented, and this tab is how you tell which.")
    if not run["tables"]:
        st.info("No sheet data captured yet.")
    for grab in run["tables"]:
        head = (f"call #{grab['call']} · {grab['agent']} · {grab['tool']} · "
                f"{len(grab['rows'])} row(s)")
        with st.expander(head, expanded=True):
            st.caption(f"args: {json.dumps(grab['args'], default=str)[:300]}")
            rows = grab["rows"]
            if len(rows) > 1:
                st.markdown(table_html(rows[0], rows[1:]), unsafe_allow_html=True)
            else:
                st.write(rows)

# ----------------------------------------------------- COST AND TOKENS ----
with tabs[6]:
    st.markdown("#### What this question cost")
    convos = run["convos"]
    tok_in = sum(c["in"] for c in convos)
    tok_out = sum(c["out"] for c in convos)
    cache_read = sum(c["cache_read"] for c in convos)
    cache_write = sum(c["cache_write"] for c in convos)
    turns = sum((c["num_turns"] or 0) for c in convos)
    cost = total_cost(run)

    st.markdown(
        f'<div class="gs-hero"><span class="lab">Total cost of this question, '
        f'as the SDK reports it</span><div class="fig">${cost:.4f}</div>'
        f'<div class="note">Across {len(convos)} conversation(s) and {turns} '
        f'turn(s). This app does no pricing arithmetic of its own -- the number '
        f'is <code>ResultMessage.total_cost_usd</code>, which is a RUNNING '
        f'TOTAL, so the largest value is the whole question. Adding them up '
        f'triple-counts the bill.</div></div>', unsafe_allow_html=True)

    st.markdown(
        '<div class="gs-grid">'
        + tile("Input tokens", f"{tok_in:,}", "t-blue", "billed")
        + tile("Output tokens", f"{tok_out:,}", "t-blue", "billed")
        + tile("Cache read", f"{cache_read:,}", "t-aqua", "cheaper than input")
        + tile("Cache write", f"{cache_write:,}", "t-orange", "paid once")
        + tile("Conversations", len(convos), "t-violet",
               "each delegation is a whole one")
        + tile("Cost per delegation",
               f"${cost / run['delegations']:.4f}" if run["delegations"] else "--",
               "", "what a specialist costs you", small=True)
        + "</div>", unsafe_allow_html=True)

    if convos:
        st.markdown("#### Conversation by conversation")
        st.caption("The router's conversation is the one that ends last and "
                   "carries the running total. The others are the specialists' "
                   "own sessions -- separate histories, separately billed.")
        peak = max(max(c["in"] + c["cache_read"], c["out"]) for c in convos) or 1
        rows = []
        for c in convos:
            total_input = c["in"] + c["cache_read"] + c["cache_write"]
            rows.append([
                c["n"], (c["session_id"] or "")[:8] or "--",
                c["num_turns"] if c["num_turns"] is not None else "--",
                f"{c['in']:,}", f"{c['out']:,}", f"{c['cache_read']:,}",
                f"{c['cache_write']:,}", bar(total_input, peak),
                f"{(c['duration_ms'] or 0):,}",
                f"${c['running_cost']:.4f}",
                (c["terminal_reason"] or c["subtype"] or "--"),
            ])
        st.markdown(table_html(
            ["#", "session", "turns", "in", "out", "cache read", "cache write",
             "input size", "ms", "running $", "ended"],
            rows, numeric={0, 2, 3, 4, 5, 6, 8, 9}), unsafe_allow_html=True)
        st.caption("The bar is one measure -- total input tokens for that "
                   "conversation -- against the largest in the column. It is a "
                   "meter, not a chart: it says which conversation carried the "
                   "context, which is usually the router's.")

    if state["history"]:
        st.markdown("#### Every question asked in this window")
        rows = [[i, short(h["question"], 70), h["delegations"], len(h["calls"]),
                 f"${total_cost(h):.4f}",
                 (h["row"][4] if h["row"] else "--")]
                for i, h in enumerate(state["history"], 1)]
        rows.append(["", "TOTAL", sum(h["delegations"] for h in state["history"]),
                     sum(len(h["calls"]) for h in state["history"]),
                     f"${sum(total_cost(h) for h in state['history']):.4f}", ""])
        st.markdown(table_html(
            ["#", "Question", "Delegations", "Tool calls", "Cost", "Action by"],
            rows, numeric={0, 2, 3, 4}), unsafe_allow_html=True)

# -------------------------------------------------- TICKET AND HANDOFF ----
with tabs[7]:
    st.markdown("#### The row that went into the Tickets tab")
    st.caption("Read off the WRITE call itself, not off what the Skill asked "
               "for. A Skill is a request; this is what the agent actually sent.")
    who, valid = action_by(run)
    if not run["row"]:
        st.warning("No ticket row seen in this run. Every case is supposed to "
                   "end in exactly one -- including the dull ones. A run with "
                   "no ticket is a case nobody can audit.")
    else:
        columns = SHEET_SCHEMA["Tickets"]["columns"]
        st.markdown(table_html(columns, [run["row"]]), unsafe_allow_html=True)
        if not valid:
            st.error(f"Action By is {run['row'][4]!r} -- neither "
                     f"{ACTED_BY_AI!r} nor {ACTED_BY_HUMAN!r}. That cell is not "
                     f"a dropdown value: it will not filter, it will not count, "
                     f"and no handoff will be sent.")
        elif who == ACTED_BY_AI:
            st.success("A rule in the rulebook covered this case, so the agent "
                       "decided it and said so on the row.")
        else:
            st.warning("Nobody has decided yet. The reply still went to the "
                       "customer -- what changed is who owns the outcome.")
    if run["second_ticket"]:
        old, new = run["second_ticket"]
        st.error(f"Two tickets in one conversation: {old} then {new}. "
                 f"One conversation is one case. Delete the extra row.")

    st.markdown("#### The handoff")
    st.caption("Only fires when Action By = Human. A webhook that fires on "
               "every ticket is one nobody reads.")
    hook = run["webhook"]
    if hook is None:
        st.info("Not sent -- either the case was the agent's, or the run has "
                "not finished.")
    elif hook["ok"]:
        st.success(f"POSTed to the escalation webhook · HTTP {hook['status']} · "
                   f"{hook['detail']}")
    else:
        st.error(f"{hook['status']} -- {hook['detail']}")
    if hook:
        st.markdown("**The exact payload that was sent**")
        st.json(hook["payload"], expanded=True)

    st.markdown("#### The Slack post")
    st.caption("The same trigger, a second destination: the workflow gets the "
               "structured payload, the channel gets the people who work it.")
    slack = run["slack"]
    if slack is None:
        st.info("Not sent -- either the case was the agent's, or the run has "
                "not finished.")
    elif slack["ok"]:
        st.success(f"Posted to {slack['channel']} · {slack['detail']}")
    else:
        st.error(f"{slack['status']} -- {slack['detail']}")
        st.caption("Slack answers HTTP 200 even when it refuses to post, so "
                   "the status code alone would have reported this as a "
                   "success. `ok` in the body is the only honest signal.")
    if slack and slack.get("payload"):
        with st.expander("the exact Slack request body"):
            st.json(slack["payload"], expanded=False)
    elif run["row"]:
        st.markdown("**What WOULD be sent, if this case were escalated**")
        st.json(escalation_payload(run), expanded=False)
    st.markdown(card(
        "Why Python sends this and not an agent",
        "<p>A Skill saying \"notify a human\" is a request with a failure rate. "
        "<code>if action_by == \"Human\"</code> is not. And the agent never "
        "gets a POST-anywhere tool: the destination and the payload shape are "
        "both fixed in code, so a confused model cannot mail your customer "
        "list to an address it invented.</p>"
        "<p>The email is best-effort -- it is not one of the five ticket "
        "columns, so it is matched out of the specialist's report with a "
        "bounded regex. Null rather than invented.</p>"), unsafe_allow_html=True)

# ------------------------------------------------------------ RAW JSON ----
with tabs[8]:
    st.markdown("#### The raw message stream")
    st.caption("Every object the SDK yielded, in arrival order, converted to "
               "plain JSON so it can be searched and diffed. This is the source "
               "every other tab is derived from -- if a tile and this disagree, "
               "this one is right.")
    if not run["raw"]:
        st.info("Nothing yet.")
    else:
        blob = json.dumps(run["raw"], indent=2, default=str)
        one, two = st.columns([1, 1])
        with one:
            st.download_button("Download the whole stream (.json)", blob,
                               file_name=f"d20_stream_{int(time.time())}.json",
                               mime="application/json", width="stretch")
        with two:
            st.download_button(
                "Download the tool calls (.json)",
                json.dumps(run["calls"], indent=2, default=str),
                file_name=f"d20_toolcalls_{int(time.time())}.json",
                mime="application/json", width="stretch")
        st.caption(f"{len(run['raw'])} messages · {len(blob):,} characters")
        for i, message in enumerate(run["raw"], 1):
            kind = message.get("__type__", "?") if isinstance(message, dict) else "?"
            with st.expander(f"{i:>3}. {kind}"):
                st.json(message, expanded=False)
        st.markdown("**All of it, in one block**")
        st.code(blob[:200000], language="json")

# -------------------------------------------------------- HOW IT WORKS ----
with tabs[9]:
    st.markdown("#### How the Agent SDK runs this")
    st.markdown(
        '<div class="gs-two">'
        + card("There is no loop in this file",
               "<p>The whole run is one <code>async for message in "
               "query(prompt, options)</code>. The SDK owns the loop: it sends "
               "the prompt, gets a response, notices the model asked for a "
               "tool, runs it, feeds the result back, and goes round again "
               "until the model stops asking. A turn is one lap.</p>"
               "<p>So the app never decides what happens next. It reads what "
               "already happened, which is why every number here can be "
               "checked against the RAW JSON tab.</p>")
        + card("The SDK runs on the Claude Code CLI",
               "<p><code>claude-agent-sdk</code> is a Python wrapper around the "
               "<code>claude</code> CLI, which is why Node has to be installed "
               "and why <code>cwd</code> and <code>setting_sources=['project']</code> "
               "matter: that is how <code>.claude/skills/</code> in this folder "
               "gets found at all.</p>")
        + card("The five message types you see in the stream",
               "<p><b>SystemMessage(init)</b> -- the session's opening "
               "snapshot: skills loaded, subagents registered, MCP servers and "
               "their status, the tool catalogue.<br>"
               "<b>AssistantMessage</b> -- the model talking: TextBlock for "
               "words, ToolUseBlock for a tool it wants run.<br>"
               "<b>UserMessage</b> -- carries ToolResultBlock, the answer that "
               "went back to the model.<br>"
               "<b>ResultMessage</b> -- one per conversation, with turns, "
               "usage and cost.</p>")
        + card("How a tool call actually works",
               "<p>1. The model emits a <b>ToolUseBlock</b>: a name and a JSON "
               "argument object it wrote itself.<br>"
               "2. The SDK checks it against <code>allowed_tools</code> and the "
               "agent's <code>disallowedTools</code>.<br>"
               "3. It calls the tool -- here, over MCP to the sheets "
               "subprocess.<br>"
               "4. The answer comes back as a <b>ToolResultBlock</b> carrying "
               "the same <code>tool_use_id</code>, which is how the TOOL CALLS "
               "tab pairs them and times them.<br>"
               "5. The model reads the result and decides what to do next.</p>"
               "<p>Nothing in this project names a sheets tool. The specialists "
               "are handed the server's whole catalogue and pick.</p>")
        + card("Delegation is just another tool",
               "<p>The router does not 'spawn' anything. It calls a tool named "
               "<code>Agent</code> with a <code>subagent_type</code> and a "
               "<code>prompt</code>. The SDK opens a SEPARATE conversation for "
               "that specialist -- its own history, its own Skill, its own "
               "ResultMessage and its own bill.</p>"
               "<p>The specialist shares no memory with the router. Whatever is "
               "not in that prompt is not known, which is why the order ID gets "
               "repeated by hand. Only the specialist's final text comes back; "
               "the router never sees its raw tool results.</p>"
               "<p>Every message from inside a delegation carries the Agent "
               "call's id as <code>parent_tool_use_id</code>. That is how each "
               "line in the stream is attributed to a name rather than guessed.</p>")
        + card("What MCP is doing here",
               "<p>The sheets server is a subprocess (<code>uvx "
               "mcp-google-sheets</code>) speaking the Model Context Protocol. "
               "The SDK asks it for its tool list and exposes them as "
               "<code>mcp__sheets__*</code>.</p>"
               "<p>The service-account key is an env var on that SUBPROCESS. No "
               "agent ever sees it, so no prompt can leak it. "
               "<code>MCP_CONNECTION_NONBLOCKING=0</code> makes the session "
               "wait for it -- on the default the specialists start while it is "
               "still connecting and burn their turns retrying.</p>")
        + card("Skills, and why they are not guarantees",
               "<p>A Skill is a Markdown file the agent loads and follows. It "
               "says HOW TO BEHAVE: which tab to read, what to report, what "
               "never to touch.</p>"
               "<p>It is a REQUEST with a non-zero failure rate. "
               "<code>disallowedTools</code> is the guarantee. Both are used "
               "here, and the AGENTS tab shows exactly which line is doing "
               "which job.</p>")
        + card("Why every case files a ticket",
               "<p>Answered fully, could not answer, no order ID given, order "
               "not in the sheet -- all four write a row. The dull rows matter "
               "as much as the interesting ones: without them, 'the agent "
               "handled it' is a claim nobody can check, and you cannot count "
               "what fraction of cases needed a person -- the one number that "
               "tells you whether the rulebook is any good.</p>")
        + "</div>", unsafe_allow_html=True)

    st.markdown("#### The three escalation triggers")
    st.markdown(table_html(
        ["#", "Trigger", "What the ticket says"],
        [[1, "The customer asks for a human, or to escalate", ACTED_BY_HUMAN],
         [2, "The rulebook does not cover the case -- outside the window, "
             "an order that has not been delivered yet, a 0% category, damage, "
             "a wrong item, anything it does not mention",
          ACTED_BY_HUMAN],
         [3, "No progress -- order not_found, a specialist errored, today's "
             "date missing, going in circles", ACTED_BY_HUMAN],
         ["--", "None of the above fired: a rule covered it and the agent "
                "decided", ACTED_BY_AI]], numeric={0}), unsafe_allow_html=True)
    st.caption("None of them stop the agent replying. What changes is one "
               "column. 'Not covered' does not mean say no -- it means you do "
               "not decide. Refusing money is as consequential as paying it.")


# ==========================================================================
# 7. WHERE THE RUN USED TO LIVE
#    It ran here, after the whole page, driven by a "pending" flag and two
#    st.rerun() calls -- one to show the question, one to show the answer.
#    That is a form submit, not a chat: the transcript was torn down and
#    rebuilt twice per message.
#
#    execute_turn() now runs inside the Run tab instead, in the same pass that
#    received the message. The bubble fills in where it already sits, and the
#    remaining ten tabs draw afterwards from the finished run -- so they are
#    current without a second pass over the page.
# ==========================================================================
