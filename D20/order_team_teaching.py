"""
order_team_teaching.py  --  HUMAN-IN-THE-LOOP & ESCALATION   (Day 20)

    you -> router -Agent tool-> order-lookup    reads the Order tab
                  -Agent tool-> delay-analyst   reads the Delays tab
                  -Agent tool-> ticket-writer   WRITES the Tickets tab
                                     |
                        MCP server (uvx mcp-google-sheets) -> spreadsheet

THE LESSON.  Every case ends as one row in the Tickets tab, whose last
column says WHO OWNED THE DECISION:

    Action By = Handle By AI    a rule in refund_rulebook.txt covered it
    Action By = Human           no rule covered it, so a person must decide

The agent never pauses.  The human-in-the-loop is RECORDED, not enforced --
section 6 is the exact line where the case stops being the agent's.

    uv run order_team_teaching.py     (setup + sheet layout: cmd.txt)
"""

import asyncio
import os
from datetime import date

from dotenv import load_dotenv
from claude_agent_sdk import AgentDefinition, ClaudeAgentOptions, query
from claude_agent_sdk.types import (
    AssistantMessage, ResultMessage, TextBlock, ToolUseBlock)

load_dotenv()

# ---- 1. SETTINGS --------------------------------------------------------

MODEL = "claude-haiku-4-5-20251001"
MAX_TURNS = 30
MAX_OUTPUT_TOKENS = 2024

# The CLI renamed the delegation tool from "Task" to "Agent" and answers to
# both.  Get the name wrong and a delegation silently does not count as one.
DELEGATE_TOOLS = ("Agent", "Task")

# The two dropdown values in the Tickets tab, spelled EXACTLY as the sheet
# spells them.  Change the dropdown and you must change both SKILL.md files:
# nothing in Python checks it.
ACTED_BY_AI = "Handle By AI"
ACTED_BY_HUMAN = "Human"

# The tools that put VALUES in cells.  Names arrive as "mcp__sheets__..." so
# we match the tail.  add_rows is deliberately NOT here: it takes a row COUNT,
# not data, so it inserts a BLANK row and records nothing.
WRITE_TOOLS = ("update_cells", "batch_update_cells")

# The readers may not delegate onward and may not write.  The only hard
# boundary in this file -- everything else is a sentence in a Skill.
NO_ACTION = [*DELEGATE_TOOLS, "mcp__sheets__update_cells",
             "mcp__sheets__batch_update_cells"]

TODAY = date.today().isoformat()          # a model has no clock
SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
SERVICE_ACCOUNT_PATH = os.getenv("SERVICE_ACCOUNT_PATH")
HERE = os.path.dirname(os.path.abspath(__file__))

# ---- 2. THE POLICY: a text file, not code -------------------------------
# No refund percentage appears in this file or in any SKILL.md.  One copy,
# and the person who owns refund policy edits a .txt, never a Skill.

RULEBOOK_PATH = os.path.join(HERE, "refund_rulebook.txt")
try:
    with open(RULEBOOK_PATH, encoding="utf-8") as fh:
        RULEBOOK = fh.read().strip()
except OSError as exc:
    # A missing rulebook does not give you a broken run you would notice --
    # it gives you a confident agent inventing refund percentages.
    raise SystemExit(f"refund_rulebook.txt is missing or unreadable: {exc}")

# The sheet ID is CONFIGURATION, so it goes in the prompt, not the question.
WHERE_THE_DATA_IS = (
    f"The order data lives in Google spreadsheet ID {SHEET_ID}. Always use "
    "that spreadsheet and never ask anyone for a spreadsheet ID.")

# ---- 3. THE THREE SPECIALISTS -------------------------------------------
# `description` is what the ROUTER reads when choosing who to hand the job
# to.  `prompt` is ALL the context that specialist will ever have -- it shares
# no memory with the router.  No tools=[...]: naming the tool would mean WE
# chose it, so each one sees the server's catalogue and picks for itself.

SUBAGENTS = {
    "order-lookup": AgentDefinition(
        description=(
            "Looks up ONE order in the Order tab and reports its status, "
            "carrier, ETA, category and order date. Use this first for any "
            "order question, including refunds. Returns 'not_found' if the "
            "order ID is not in the sheet."),
        prompt=("You are an order-lookup specialist reporting to another "
                f"agent. {WHERE_THE_DATA_IS} Read the 'Order' tab only."),
        skills=["order-lookup"], mcpServers=["sheets"],
        disallowedTools=NO_ACTION, model=MODEL),
    "delay-analyst": AgentDefinition(
        description=(
            "Reads the Delays tab and reports WHY one order is late. Use only "
            "after order-lookup reports a delayed status. Returns "
            "'no_reason_logged' if no reason has been written down yet."),
        prompt=("You are a delay-analysis specialist reporting to another "
                f"agent. {WHERE_THE_DATA_IS} Read the 'Delays' tab only."),
        skills=["delay-analysis"], mcpServers=["sheets"],
        disallowedTools=NO_ACTION, model=MODEL),
    # The ONLY agent that writes.  Everyone else reads.
    "ticket-writer": AgentDefinition(
        description=(
            "Appends one row to the Tickets tab recording what happened and "
            "who decided it. Use LAST, once per customer case, after the "
            "answer is known. Returns the ticket ID it wrote."),
        prompt=("You are a ticketing specialist reporting to another agent. "
                f"{WHERE_THE_DATA_IS} Write to the 'Tickets' tab only. Never "
                "edit the 'Order' or 'Delays' tabs."),
        skills=["ticket-writer"], mcpServers=["sheets"],
        disallowedTools=list(DELEGATE_TOOLS), model=MODEL),
}

# ---- 4. THE ROUTER ------------------------------------------------------

options = ClaudeAgentOptions(
    model=MODEL,
    fallback_model=MODEL,
    # Three things land in the system prompt, each for its own reason:
    #   the ROLE      one sentence -- the routing lives in the Skill
    #   the DATE      a fact the model cannot look up and must not guess
    #   the RULEBOOK  policy owned by someone else, pasted in verbatim
    # SKILL.md says HOW TO BEHAVE.  The rulebook says WHAT THE POLICY IS.
    system_prompt=(
        "You are a concise order-support agent coordinating three specialists. "
        "Delegate the spreadsheet work with the Agent tool; do not read or "
        f"write the sheet yourself. Today's date is {TODAY}. Use it, and only "
        "it, when working out how old an order is -- never guess today's date."
        f"\n\nThe refund policy below is the ONLY refund policy. Follow it "
        f"exactly and never reason past it:\n\n{RULEBOOK}"),
    agents=SUBAGENTS,
    mcp_servers={"sheets": {
        "command": "uvx",
        "args": ["--with", "mcp<2", "mcp-google-sheets@latest"],
        # The credential goes to the SERVER subprocess.  No agent ever sees
        # it, so no prompt can leak it.
        "env": {"SERVICE_ACCOUNT_PATH": SERVICE_ACCOUNT_PATH},
        "alwaysLoad": True}},
    cwd=HERE,
    setting_sources=["project"],   # this + cwd is how .claude/skills/ is found
    skills=["support-router"],     # each specialist declares its own above
    env={
        # There is no max_tokens on ClaudeAgentOptions; it goes in env.
        "CLAUDE_CODE_MAX_OUTPUT_TOKENS": str(MAX_OUTPUT_TOKENS),
        # Wait for the sheets server, or the specialists start before it is up
        # and burn their turns retrying.
        "MCP_CONNECTION_NONBLOCKING": "0"},
    # ONE GLOBAL approval list.  "mcp__sheets__*" approves the WRITE tools for
    # every agent, including the two that must never write.  Only NO_ACTION
    # above actually stops them -- a Skill is a REQUEST, not a guarantee.
    allowed_tools=[*DELEGATE_TOOLS, "mcp__sheets__*", "Skill(order-lookup)",
                   "Skill(delay-analysis)", "Skill(ticket-writer)"],
    permission_mode="dontAsk",     # a script has nobody to answer a prompt
    max_turns=MAX_TURNS,
)

# ---- 5. THE RUN: one `async for`, and no loop of ours -------------------
# The SDK owns the agent loop: it sends the prompt, sees the model ask for a
# tool, runs it, feeds the result back, and goes round again.  A turn is one
# lap.  Everything below only READS what that loop produced.

async def run_team(question: str) -> None:
    print(f"\n{'=' * 66}\nQUESTION: {question}\n{'=' * 66}")
    delegations, reply, ticket_row, verdict = 0, "", [], None

    async for msg in query(prompt=question, options=options):
        if isinstance(msg, ResultMessage):
            verdict = msg          # nested ones too; the LAST is the whole run
        elif isinstance(msg, AssistantMessage):
            # parent_tool_use_id is None only for the router itself.
            from_router = getattr(msg, "parent_tool_use_id", None) is None
            for block in msg.content:
                if isinstance(block, TextBlock) and block.text.strip():
                    if from_router:
                        reply = block.text          # what the customer hears
                elif not isinstance(block, ToolUseBlock):
                    continue
                elif block.name in DELEGATE_TOOLS:
                    delegations += 1
                elif block.name.endswith(WRITE_TOOLS):
                    # A Skill ORDERS a ticket, and a Skill is a REQUEST -- so
                    # read the row off the write the agent ACTUALLY sent.
                    # update_cells keeps rows in "data"; batch_update_cells
                    # nests them one level deeper under "ranges".
                    rows = block.input.get("data") or []
                    if not rows:
                        for cells in (block.input.get("ranges") or {}).values():
                            rows = cells
                            break
                    # Ticket ID | Order ID | Issue | Resolution | Action By
                    for row in rows:
                        if isinstance(row, list) and len(row) >= 5:
                            ticket_row = row
                            break

    print(f"\n{reply}\n")
    print(f"delegations: {delegations}   "
          f"ticket: {ticket_row[0] if ticket_row else 'NONE'}")
    if verdict:
        print(f"terminal_reason: {verdict.terminal_reason}   "
              f"cost: ${verdict.total_cost_usd or 0:.4f}")
        if verdict.terminal_reason != "completed":
            print("WARNING: this run did NOT succeed -- investigate.")
    who_owns_it(ticket_row)


# =========================================================================
#  6.  >>>>>>>>  T H E   H U M A N - I N - T H E - L O O P  <<<<<<<<
# =========================================================================
# THIS IS THE LINE THE WHOLE DAY IS ABOUT.  Everything above answered the
# customer; this decides who OWNS that answer -- and it is decided in PYTHON,
# not by the model:
#
#   Handle By AI   a rule in the rulebook covered it, the agent decided
#   Human          no rule covered it.  The agent still replied, but the
#                  DECISION was never its own to make
#
# Note WHERE the check lives.  A sentence in a Skill saying "escalate when
# unsure" is a REQUEST with a failure rate.  `if action_by == ACTED_BY_HUMAN`
# is an if-statement: it runs every time and no confused model can talk its
# way past it.  That is the difference between asking and enforcing.
#
# In production this branch is where you notify a person -- webhook, Slack,
# pager.  order_team_streamlit.py does exactly that.  Left out here so the
# ONE decision stays visible with nothing beside it.

BLUE, BOLD, OFF = "\033[94m", "\033[1m", "\033[0m"


def who_owns_it(ticket_row: list) -> None:
    if not ticket_row:
        # Every case is meant to end in exactly one row, including the dull
        # ones.  A case with no ticket is one nobody can audit.
        print(f"{BOLD}NO TICKET{OFF} -- nothing recorded, nothing to audit.")
        return

    action_by = ticket_row[4]

    if action_by == ACTED_BY_HUMAN:                     # <<< THE HANDOFF >>>
        print(f"\n{BLUE}{BOLD}{'=' * 66}\n"
              f"  HUMAN-IN-THE-LOOP -- this case is now a PERSON'S\n"
              f"{'=' * 66}{OFF}")
        print(f"{BLUE}  ticket  {ticket_row[0]}\n"
              f"  order   {ticket_row[1]}\n"
              f"  issue   {ticket_row[2]}\n"
              f"  a person must decide:  {ticket_row[3]}\n"
              f"  (production notifies someone here){OFF}\n")
    elif action_by == ACTED_BY_AI:
        print(f"\nHANDLED BY AI -- a rule covered it. Ticket {ticket_row[0]}, "
              f"no person needed.\n")
    else:
        # Not a dropdown value: that cell will not filter and will not count.
        print(f"\nAction By is {action_by!r} -- neither {ACTED_BY_AI!r} nor "
              f"{ACTED_BY_HUMAN!r}. That cell is broken.\n")


# ---- 7. TRY IT ----------------------------------------------------------
# Same code, different questions, and the TICKET says who owned each outcome.


async def main() -> None:
    # Outside the refund window -> no rule covers it -> Action By = Human.
    await run_team("I want a refund on order 1002, it was late.")
    # Damage is in no rule at all           -> Action By = Human
    # await run_team("Order 3001 arrived damaged. Can I get a refund?")
    # No order ID: it asks, and STILL files -> Action By = Handle By AI
    # await run_team("I want a refund on something I ordered last week.")


if __name__ == "__main__":
    # Fail loudly, or every sheet call 404s inside a specialist.
    if not SERVICE_ACCOUNT_PATH or not os.path.isfile(SERVICE_ACCOUNT_PATH):
        raise SystemExit("SERVICE_ACCOUNT_PATH is missing or wrong -- see cmd.txt")
    asyncio.run(main())
