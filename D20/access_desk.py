"""
access_desk.py  --  LEAST-PRIVILEGE ACCESS DESK   (Day 20)

    you -> router -Agent tool-> employee-identity   reads employees.json
                  -Agent tool-> entitlement-reader  reads entitlement_policy.json
                                                    and entitlements.json
                  -Agent tool-> audit-writer        APPENDS audit.jsonl
                                     |
                        in-process SDK MCP server "desk" -> local files

Structural sibling of order_team_teaching.py, with the Google Sheet replaced
by three local JSON files and one append-only audit.jsonl.

THE PIPELINE, stage by stage:

    1. request                readers verify identity and entitlement
    2. readers report         (employee-identity, entitlement-reader --
                                read-only, cannot reach the audit writer)
    3. router proposes         the router drafts a reply (model_reply) --
       a response               a PROPOSAL, not yet what anyone is told
    4. Python enforces         decide_owner() checks the proposal against
       policy                   entitlement_policy.json and the verified
                                directory. The model cannot set decision_owner;
                                there is no such argument to append_audit_ticket.
    5. writer saves ONE        record_ticket() builds the ticket from the
       validated ticket          Python verdict and writes it -- once
    6. Python checks the       verify_persisted_ticket() reads audit.jsonl
       saved ticket              back and confirms the line on disk is the
                                ticket that was just decided, not something
                                a race or a partial write left behind
    7. human notification      run_desk() re-reads the ticket by ticket_id
       if required               (get_ticket_by_id, ordinary Python, after
                                the agent's turn is over) and, only when
                                decision_owner == "Human", POSTs it to
                                APPROVER_WEBHOOK_URL (notify_human_approver,
                                section 8). Not a tool: no agent chooses to
                                call it or gets to skip it. Agent-owned
                                tickets never reach this step at all.

THE LESSON.  Every completed request ends as exactly ONE audit ticket whose
`decision_owner` column says WHO OWNED THE DECISION:

    decision_owner = "Agent"    entitlement_policy.json resolved it
    decision_owner = "Human"    the policy did not resolve it, so a person must

The agent never pauses.  The human-in-the-loop is RECORDED, not enforced --
section 7 is the exact line where the request stops being the agent's.

And note WHERE the policy runs.  A sentence in a prompt saying "escalate when
unsure" is a REQUEST with a failure rate.  decide_owner() below is ordinary
Python: it runs inside the audit tool on every ticket, it reads the JSON
policy file, and no confused model can talk its way past it.  The model is
never asked what the decision owner is -- it is not a field the model can set.

NO AGENT HAS A GRANT TOOL.  This desk decides and records; granting access is
somebody else's system, and section 2 asserts that at startup.

    uv run access_desk.py
"""

import asyncio
import json
import os
import re
from datetime import date, datetime, timezone
from typing import Any

import requests

from claude_agent_sdk import (
    AgentDefinition, ClaudeAgentOptions, HookContext, HookMatcher,
    PermissionResultAllow, PermissionResultDeny, ToolPermissionContext,
    create_sdk_mcp_server, query, tool)
from claude_agent_sdk.types import (
    AssistantMessage, ResultMessage, TextBlock, ToolUseBlock)

# No load_dotenv() and no credentials: the order team needed a service account
# to reach a Google Sheet, and this desk reads three files sitting next to it.
# Model auth comes from the CLI's own login or an ANTHROPIC_API_KEY already in
# the environment -- a stale key in a .env would only hijack a working login.

# ---- 1. SETTINGS --------------------------------------------------------

MODEL = "claude-haiku-4-5-20251001"
MAX_TURNS = 30
MAX_OUTPUT_TOKENS = 2024

# The CLI renamed the delegation tool from "Task" to "Agent" and answers to
# both.  Get the name wrong and a delegation silently does not count as one.
DELEGATE_TOOLS = ("Agent", "Task")

# The two decision_owner values, spelled EXACTLY as the assignment spells
# them.  Nothing else may ever reach the ticket -- section 5 rejects it.
OWNER_AGENT = "Agent"
OWNER_HUMAN = "Human"

TODAY = date.today().isoformat()          # a model has no clock
HERE = os.path.dirname(os.path.abspath(__file__))

POLICY_PATH = os.path.join(HERE, "entitlement_policy.json")
EMPLOYEES_PATH = os.path.join(HERE, "employees.json")
ENTITLEMENTS_PATH = os.path.join(HERE, "entitlements.json")
AUDIT_PATH = os.path.join(HERE, "audit.jsonl")

# Where a Human-owned ticket gets POSTed after the run.  Read from the
# environment, never hardcoded -- an approver endpoint is deployment
# configuration, not something this file should assume. Unset means there
# is nobody to notify yet, and notify_human_approver() says so rather than
# silently skipping.
APPROVER_WEBHOOK_URL = os.getenv("APPROVER_WEBHOOK_URL")

# The six columns every completed request must produce, in order.
TICKET_FIELDS = ("ticket_id", "requester", "resource", "action",
                 "decision_owner", "reason")


def _load(path: str) -> dict:
    """A missing data file does not give you a broken run you would notice --
    it gives you a confident agent inventing employees and policies."""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"{os.path.basename(path)} is missing or unreadable: {exc}")


POLICY = _load(POLICY_PATH)
DIRECTORY = {e["employee_id"]: e for e in _load(EMPLOYEES_PATH)["employees"]}
HELD = _load(ENTITLEMENTS_PATH)["held"]

# ---- 2. THE POLICY ENGINE: ordinary Python, not a prompt ----------------
# entitlement_policy.json is the ONLY place a sensitivity or an allowed
# department is written down.  No agent reasons its way to a decision owner;
# this function does, from that file, every single time.


def resolve_employee(requester: str) -> dict | None:
    """Match an employee by id, email or name.

    Deliberately forgiving about SHAPE and strict about IDENTITY.  An agent
    that writes "Tomas Alvarez (E-1004)" has named a real person, and letting
    the string formatting decide the answer would escalate a case the policy
    covers -- the loudest way this desk can be wrong.  A name that is not in
    the directory still matches nothing and still goes to a human.

    The "id anywhere in the text" fallback checks every id ACTUALLY IN THE
    DIRECTORY, not one hardcoded ID shape -- employees.json has both
    "E-1004" style ids and "employee-001"/"manager-001" style ids, and
    backstop() (section 7) calls this with a whole raw sentence, not a
    clean id, so this has to find either shape inside free text.
    """
    needle = (requester or "").strip().lower()
    if not needle:
        return None
    for rec in DIRECTORY.values():                       # exact id/email/name
        if needle in (rec["employee_id"].lower(), rec["email"].lower(),
                      rec["name"].lower()):
            return rec
    for rec in DIRECTORY.values():                       # an id anywhere in it
        if re.search(rf"\b{re.escape(rec['employee_id'].lower())}\b", needle):
            return rec
    for rec in DIRECTORY.values():                       # a name anywhere in it
        if rec["name"].lower() in needle or rec["email"].lower() in needle:
            return rec
    return None


def normalize_action(raw: str) -> str:
    """Pull a known action out of whatever the agent typed.

    An agent that says "read access request" means `read`, and matching that
    string against auto_approve_actions would escalate a case the policy
    plainly covers.  Anything with no known action in it comes back unchanged
    and is escalated by the unknown_action rule below -- guessing would be
    the one direction this must never fail in.
    """
    text = (raw or "").strip().lower()
    known = POLICY["known_actions"]
    if text in known:
        return text
    words = set(re.findall(r"[a-z]+", text))
    # "speak_to_manager" is two words, not one, so it cannot be found by the
    # single-word scan below.  Checked as a WORD SET, not a fixed phrase
    # list: "speak with manager", "speak to a manager" and "requested to
    # speak with manager about a raise" all contain {"speak", "manager"}
    # even though no two of them share an exact substring.
    manager_word = {"manager", "managers"}
    intent_word = {"speak", "talk", "escalate", "escalation"}
    if words & manager_word and words & intent_word:
        return "speak_to_manager"
    for action in known:
        if action in words:
            return action
    return text


def already_holds(employee_id: str, resource: str, action: str) -> bool:
    for grant in HELD.get(employee_id, []):
        if grant["resource"] == resource and action in grant["actions"]:
            return True
    return False


def decide_owner(requester: str, resource: str, action: str,
                 target: str = "") -> dict:
    """Return the AUTHORITATIVE ticket facts for one request.

    Every branch that is not a clean policy match returns OWNER_HUMAN.  The
    default is escalation, so a case this function has not thought about
    lands on a person rather than being quietly auto-approved.

    `target` is who the action lands ON -- only meaningful for a
    self_service_only resource (own-password, own-account), where the
    policy is "the requester's own account" and nothing wider.  It is
    required, not assumed: an empty target on a self-service resource does
    not default to "must be the requester", it escalates.
    """
    rules = POLICY["escalation_rules"]
    resources = POLICY["resources"]
    action = normalize_action(action)

    person = resolve_employee(requester)
    if person is None:
        return {"requester": (requester or "unknown").strip() or "unknown",
                "decision_owner": OWNER_HUMAN,
                "reason": f"requester {requester!r} is not in the employee "
                          f"directory ({rules['unknown_requester']} rule)"}

    who = f"{person['employee_id']} ({person['name']})"

    if person["employment_status"] not in POLICY["employment_statuses_allowed"]:
        return {"requester": who, "decision_owner": OWNER_HUMAN,
                "reason": f"employment_status is {person['employment_status']!r}, "
                          f"not active ({rules['inactive_requester']} rule)"}

    # Unconditional overrides.  These fire on the ACTION alone, before any
    # resource lookup, because "always requires Human" means always -- there
    # is no resource-specific escape hatch for either of them.
    if action == "speak_to_manager":
        return {"requester": who, "decision_owner": OWNER_HUMAN,
                "reason": "requests to speak with a manager always require "
                          f"Human ({rules['manager_escalation']} rule)"}

    if action == "admin":
        return {"requester": who, "decision_owner": OWNER_HUMAN,
                "reason": "any admin-role grant always requires Human "
                          f"({rules['admin_role_grant']} rule)"}

    spec = resources.get(resource)
    if spec is None:
        return {"requester": who, "decision_owner": OWNER_HUMAN,
                "reason": f"resource {resource!r} is not in "
                          f"entitlement_policy.json ({rules['unknown_resource']} rule)"}

    # Checked BEFORE the action even has to be recognised, and BEFORE
    # already_holds.  A resource marked "always Human" (Finance-Admins,
    # payroll-ledger, prod-database) must escalate no matter what action
    # word came with the request and even for someone who already holds
    # it -- "always" allows no already-a-member exception and no benefit
    # of the doubt for a garbled action, or reconfirming sensitive access
    # would quietly skip the human every request after the first.
    if spec["requires_human_approval"]:
        return {"requester": who, "decision_owner": OWNER_HUMAN,
                "reason": f"{resource!r} is {spec['sensitivity']} sensitivity and "
                          f"entitlement_policy.json marks it requires_human_approval"}

    if action not in POLICY["known_actions"]:
        return {"requester": who, "decision_owner": OWNER_HUMAN,
                "reason": f"action {action!r} is not one of "
                          f"{POLICY['known_actions']} ({rules['unknown_action']} rule)"}

    if spec.get("self_service_only"):
        target_text = (target or "").strip()
        if not target_text:
            return {"requester": who, "decision_owner": OWNER_HUMAN,
                    "reason": f"{resource!r} is self-service only and no "
                              f"target was named; nothing confirms this is "
                              f"the requester's own account "
                              f"({rules['outside_self_service_policy']} rule)"}
        target_person = resolve_employee(target_text)
        if (target_person is None
                or target_person["employee_id"] != person["employee_id"]):
            return {"requester": who, "decision_owner": OWNER_HUMAN,
                    "reason": f"{resource!r} only covers the requester's own "
                              f"account, and the target ({target_text!r}) is "
                              f"not {person['name']} "
                              f"({rules['self_service_not_self']} rule)"}
        if action not in spec["auto_approve_actions"]:
            return {"requester": who, "decision_owner": OWNER_HUMAN,
                    "reason": f"action {action!r} on {resource!r} is outside "
                              f"the explicit self-service policy "
                              f"({rules['outside_self_service_policy']} rule)"}
        return {"requester": who, "decision_owner": OWNER_AGENT,
                "reason": f"entitlement_policy.json auto-approves self-service "
                          f"{action!r} on {resource!r} for {person['name']}"}

    if already_holds(person["employee_id"], resource, action):
        return {"requester": who, "decision_owner": OWNER_AGENT,
                "reason": f"{person['name']} already holds {action!r} on "
                          f"{resource!r}; nothing to change"}

    if person["department"] not in spec["allowed_departments"]:
        return {"requester": who, "decision_owner": OWNER_HUMAN,
                "reason": f"department {person['department']!r} is not in the "
                          f"allowed_departments for {resource!r}"}

    if person["role"] in spec["denied_roles"]:
        return {"requester": who, "decision_owner": OWNER_HUMAN,
                "reason": f"role {person['role']!r} is denied on {resource!r} "
                          f"by entitlement_policy.json"}

    if action not in spec["auto_approve_actions"]:
        return {"requester": who, "decision_owner": OWNER_HUMAN,
                "reason": f"action {action!r} is not in auto_approve_actions "
                          f"{spec['auto_approve_actions']} for {resource!r}"}

    return {"requester": who, "decision_owner": OWNER_AGENT,
            "reason": f"entitlement_policy.json auto-approves {action!r} on "
                      f"{resource!r} for {person['department']} / {person['role']}"}


def validate_ticket(ticket: dict) -> None:
    """A ticket missing a column is a request nobody can audit."""
    missing = [f for f in TICKET_FIELDS if not ticket.get(f)]
    if missing:
        raise ValueError(f"ticket is missing {missing}")
    if ticket["decision_owner"] not in (OWNER_AGENT, OWNER_HUMAN):
        raise ValueError(f"decision_owner {ticket['decision_owner']!r} is neither "
                         f"{OWNER_AGENT!r} nor {OWNER_HUMAN!r}")


# ---- 3. THE TOOLS: four readers, one writer, no granter -----------------
# In-process SDK tools instead of an external MCP server -- the data is three
# local JSON files, so there is nothing to spawn.  The tool names the agents
# see are "mcp__desk__<name>".

TOOL_PREFIX = "mcp__desk__"

# Run-scoped state.  The writer tool consults it to enforce ONE ticket per
# request; nothing about it is visible to a model.
CURRENT_CASE: dict[str, Any] = {}


@tool("lookup_employee", "Look up ONE employee by id, email or name and return "
      "their department, role, manager and employment status.",
      {"requester": str})
async def lookup_employee(args: dict) -> dict:
    person = resolve_employee(args.get("requester", ""))
    body = json.dumps(person or {"result": "not_found"}, indent=2)
    return {"content": [{"type": "text", "text": body}]}


@tool("list_employees", "List every employee id and name in the directory.", {})
async def list_employees(args: dict) -> dict:
    body = json.dumps([{"employee_id": e["employee_id"], "name": e["name"],
                        "department": e["department"]}
                       for e in DIRECTORY.values()], indent=2)
    return {"content": [{"type": "text", "text": body}]}


@tool("read_entitlement_policy", "Read entitlement_policy.json. Pass a resource "
      "id for one resource, or leave it empty for the whole policy.",
      {"resource": str})
async def read_entitlement_policy(args: dict) -> dict:
    resource = (args.get("resource") or "").strip()
    if not resource:
        body = json.dumps(POLICY, indent=2)
    else:
        spec = POLICY["resources"].get(resource)
        body = json.dumps(
            {"resource": resource, **spec} if spec else
            {"resource": resource, "result": "not_in_policy",
             "known_resources": sorted(POLICY["resources"])}, indent=2)
    return {"content": [{"type": "text", "text": body}]}


@tool("read_held_entitlements", "Read the entitlements one employee already "
      "holds today.", {"employee_id": str})
async def read_held_entitlements(args: dict) -> dict:
    emp = (args.get("employee_id") or "").strip()
    body = json.dumps({"employee_id": emp, "held": HELD.get(emp, [])}, indent=2)
    return {"content": [{"type": "text", "text": body}]}


@tool("append_audit_ticket", "Validate and record ONE audit ticket for this "
      "request. For a self-service action (reset on own-password, unlock on "
      "own-account) target must be who the action affects -- leave it blank "
      "for anything else. Call this exactly once, last.",
      {"requester": str, "resource": str, "action": str, "target": str,
       "agent_note": str})
async def append_audit_ticket(args: dict) -> dict:
    """The only writer in the file, and the only WRITE this tool performs.

    Note what this signature does NOT take: decision_owner and reason.  They
    are not fields a model may set, so there is no argument to smuggle
    "Agent" through for a case the policy sends to a person -- proposing one
    is not a request this schema can even express.  Validation happens
    first, in Python, against entitlement_policy.json and the verified
    employee directory (decide_owner, called from record_ticket below);
    only the validated result is ever written.  There is no earlier ticket
    with a provisional label sitting on disk to correct afterward -- the
    write in record_ticket is the first and only write.
    """
    if CURRENT_CASE.get("ticket"):
        return {"is_error": True, "content": [{"type": "text", "text":
                f"REFUSED: this request already has ticket "
                f"{CURRENT_CASE['ticket']['ticket_id']}. One ticket per request."}]}

    ticket = record_ticket(args.get("requester", ""), args.get("resource", ""),
                           args.get("action", ""), args.get("target", ""),
                           args.get("agent_note", ""))
    visible = {f: ticket[f] for f in TICKET_FIELDS}
    return {"content": [{"type": "text", "text": json.dumps(visible, indent=2)}]}


def record_ticket(requester: str, resource: str, action: str,
                  target: str = "", agent_note: str = "") -> dict:
    """Validate the proposed request against policy, then append the one
    ticket that validation produced. Decide -> build -> validate -> write,
    in that order, once. Nothing between the decision and the disk.
    """
    verdict = decide_owner(requester, resource, action, target)     # VALIDATE
    ticket = {                                                      # BUILD
        "ticket_id": next_ticket_id(),
        "requester": verdict["requester"],
        "resource": (resource or "unspecified").strip(),
        "action": normalize_action(action) or "unspecified",
        "decision_owner": verdict["decision_owner"],
        "reason": verdict["reason"],
        # Everything past the six required columns is context, not decision.
        "target": (target or "").strip(),
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "policy_version": POLICY["policy_version"],
        "request_text": CURRENT_CASE.get("request", ""),
        "agent_note": (agent_note or "").strip(),
    }
    validate_ticket(ticket)                                         # VALIDATE
    with open(AUDIT_PATH, "a", encoding="utf-8") as fh:              # WRITE
        fh.write(json.dumps(ticket) + "\n")
    verify_persisted_ticket(ticket)                                  # VERIFY
    CURRENT_CASE["ticket"] = ticket
    if ticket["decision_owner"] == OWNER_AGENT:
        simulate_self_service(ticket)
    return ticket


def verify_persisted_ticket(ticket: dict) -> None:
    """Read audit.jsonl back and confirm the line just written IS this
    ticket -- not "probably is", read back and compared field for field.

    validate_ticket() checks the ticket is well-formed before the write.
    This checks the write itself: a full disk, a concurrent writer, or a
    truncated line would make what is on disk disagree with what Python
    just decided, and record_ticket has no business calling that request
    handled until the audit trail actually says what it thinks it says.
    """
    try:
        with open(AUDIT_PATH, encoding="utf-8") as fh:
            last = None
            for line in fh:
                if line.strip():
                    last = line
    except OSError as exc:
        raise RuntimeError(f"audit.jsonl unreadable right after writing "
                           f"ticket {ticket['ticket_id']}: {exc}") from exc
    on_disk = json.loads(last) if last else None
    if on_disk != ticket:
        raise RuntimeError(
            f"persisted ticket does not match what record_ticket built for "
            f"{ticket['ticket_id']}: on disk = {on_disk!r}")


SELF_SERVICE_LABELS = {
    ("own-password", "reset"): "password reset",
    ("own-account", "unlock"): "account unlock",
}


def simulate_self_service(ticket: dict) -> None:
    """Run the routine operation an Agent-owned ticket just approved --
    LOCALLY, in this process, and nowhere else.

    This is the only place any operation "runs".  It only ever fires for a
    self_service_only resource (decide_owner never marks anything else
    Agent-owned without a matching real system to call, and this file has
    none), and it never claims a real account or a real system changed --
    the printed line says "simulated" every time, on purpose.
    """
    spec = POLICY["resources"].get(ticket["resource"], {})
    if not spec.get("self_service_only"):
        return
    label = SELF_SERVICE_LABELS.get(
        (ticket["resource"], ticket["action"]),
        f"{ticket['resource']}:{ticket['action']}")
    print(f"[tool] {label} simulated locally for {ticket['requester']} "
          f"(ticket {ticket['ticket_id']}) -- no real account or permission "
          f"was changed")


def get_ticket_by_id(ticket_id: str) -> dict | None:
    """Read audit.jsonl and return the ticket with this id, or None.

    Deliberately independent of CURRENT_CASE or anything else held in
    memory -- this is the same lookup a separate notifier process would do,
    reading only the file record_ticket wrote and verify_persisted_ticket
    already confirmed.
    """
    match = None
    try:
        with open(AUDIT_PATH, encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("ticket_id") == ticket_id:
                    match = row
    except (OSError, json.JSONDecodeError):
        return None
    return match


def notify_human_approver(ticket: dict) -> None:
    """POST one Human-owned ticket to APPROVER_WEBHOOK_URL.

    Called from ordinary Python, after the agent's turn is over, keyed off
    ticket["decision_owner"] as read back from disk -- never a tool, so no
    agent ever decides whether this runs. Silence is not an option either
    way: configured-and-sent, configured-and-failed, and not-configured
    each print their own unambiguous line, and none of the three is worded
    as success unless the POST actually got a 2xx back.
    """
    if not APPROVER_WEBHOOK_URL:
        print(f"{BOLD}[notify] NOT SENT{OFF} -- ticket {ticket['ticket_id']}: "
              f"APPROVER_WEBHOOK_URL is not set, so no approver was notified.")
        return

    payload = {**{f: ticket[f] for f in TICKET_FIELDS},
              "target": ticket.get("target", "")}
    try:
        resp = requests.post(APPROVER_WEBHOOK_URL, json=payload, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"{BOLD}[notify] FAILED{OFF} -- ticket {ticket['ticket_id']} "
              f"was NOT delivered to the approver webhook: {exc}")
        return

    print(f"[notify] sent ticket {ticket['ticket_id']} to the approver "
          f"webhook (HTTP {resp.status_code})")


def next_ticket_id() -> str:
    """AUD-1 for the first ticket ever, counting the lines already on disk."""
    try:
        with open(AUDIT_PATH, encoding="utf-8") as fh:
            n = sum(1 for line in fh if line.strip())
    except OSError:
        n = 0
    return f"AUD-{n + 1}"


DESK = create_sdk_mcp_server(
    name="desk", version="1.0.0",
    tools=[lookup_employee, list_employees, read_entitlement_policy,
           read_held_entitlements, append_audit_ticket])

IDENTITY_TOOLS = [TOOL_PREFIX + "lookup_employee", TOOL_PREFIX + "list_employees"]
ENTITLEMENT_TOOLS = [TOOL_PREFIX + "read_entitlement_policy",
                     TOOL_PREFIX + "read_held_entitlements"]
AUDIT_TOOLS = [TOOL_PREFIX + "append_audit_ticket"]
ALL_DESK_TOOLS = IDENTITY_TOOLS + ENTITLEMENT_TOOLS + AUDIT_TOOLS

# No tool on this desk grants, revokes, provisions or elevates anything.  If
# somebody adds one, this fails at import rather than in production.
GRANTING = re.compile(r"grant|revoke|provision|elevate|approve|sudo|admin", re.I)
_privileged = [t for t in ALL_DESK_TOOLS if GRANTING.search(t)]
if _privileged:
    raise SystemExit(f"privileged access-granting tool exposed: {_privileged}")

# ---- 4. THE THREE SPECIALISTS -------------------------------------------
# `description` is what the ROUTER reads when choosing who to hand the job
# to.  `prompt` is ALL the context that specialist will ever have -- it shares
# no memory with the router.
#
# Unlike the order team, every agent here gets an EXPLICIT `tools` allow-list.
# An allow-list is closed: a tool that is not named cannot be called, so the
# readers cannot reach the audit writer no matter what a prompt talks them
# into.  `disallowedTools` on top of it is belt and braces -- it re-bans the
# delegation tools so no reader can start a sub-team of its own.

NO_DELEGATION = list(DELEGATE_TOOLS)

SUBAGENTS = {
    "employee-identity": AgentDefinition(
        description=(
            "Resolves WHO is asking. Looks up one employee in the directory "
            "and reports their employee id, department, role, manager and "
            "employment status. Use this FIRST for any access request. "
            "Returns 'not_found' if the person is not in the directory."),
        prompt=("You are an employee-identity reader reporting to another "
                "agent. The directory is your only source; never invent a "
                "person, a department or a status. Report exactly what the "
                "lookup returns, including 'not_found'. You read only -- you "
                "do not judge the request and you do not write anything."),
        tools=IDENTITY_TOOLS, mcpServers=["desk"],
        disallowedTools=NO_DELEGATION, model=MODEL),

    "entitlement-reader": AgentDefinition(
        description=(
            "Reads the entitlement policy for ONE resource and the "
            "entitlements an employee already holds. Use AFTER the identity "
            "is known. Returns 'not_in_policy' for an unknown resource."),
        prompt=("You are an entitlement reader reporting to another agent. "
                "Report the policy for the requested resource -- its "
                "sensitivity, allowed_departments, denied_roles, "
                "auto_approve_actions and requires_human_approval -- and what "
                "the employee already holds. Quote the policy; never "
                "paraphrase a rule into a decision. You read only. Deciding "
                "who owns the request is not your job and not the router's: "
                "it is settled in Python when the ticket is written.\n\n"
                "Two resources are self-service only: 'own-password' (action "
                "'reset') and 'own-account' (action 'unlock'). Report them "
                "like any other resource -- do not decide whether this "
                "particular request is really about the requester's own "
                "account; that check also happens in Python, from the target "
                "the audit-writer supplies."),
        tools=ENTITLEMENT_TOOLS, mcpServers=["desk"],
        disallowedTools=NO_DELEGATION, model=MODEL),

    # The ONLY agent that writes.  Everyone else reads.
    "audit-writer": AgentDefinition(
        description=(
            "Appends ONE audit ticket for the request to audit.jsonl and "
            "returns it. Use LAST, exactly once per request, after the "
            "identity and the policy are known."),
        prompt=("You are an audit-ticket writer reporting to another agent. "
                "Call append_audit_ticket exactly once with the requester "
                "(the employee id the directory returned, e.g. E-1004), "
                "the resource, the action, and target, plus a short agent_note "
                "saying what was found. The ticket's decision_owner and reason are "
                "filled in by the policy engine, not by you -- there are no "
                "such arguments, so do not try to supply them and do not "
                "predict them.\n\n"
                "target matters only for 'own-password' and 'own-account': "
                "put there whoever the identity reader confirmed the action is "
                "FOR (usually the same person as requester, for a genuine "
                "self-service request). Leave target blank for every other "
                "resource. Do not guess a target and do not assume it equals "
                "the requester -- an empty or mismatched target is Python's "
                "signal that this was not confirmed as self-service, and it "
                "will escalate to Human on purpose.\n\n"
                "Report the ticket you get back, verbatim. Never say a "
                "password was reset, an account was unlocked, or access was "
                "granted -- the ticket's decision_owner says whether that even "
                "happened."),
        tools=AUDIT_TOOLS, mcpServers=["desk"],
        disallowedTools=NO_DELEGATION, model=MODEL),
}

# ---- 5. THE PYTHON TOOL BOUNDARY ----------------------------------------
# AgentDefinition.tools above is the SDK's allow-list.  This is OURS: one
# dict, one if-statement, checked on every single tool call before it runs.
# It is the line that makes "the router must not have the audit write tool"
# a fact about the process rather than a promise in a prompt.

ROUTER = "router"
TOOL_BOUNDARY = {
    ROUTER: set(DELEGATE_TOOLS),          # delegates; reads nothing, writes nothing
    "employee-identity": set(IDENTITY_TOOLS),
    "entitlement-reader": set(ENTITLEMENT_TOOLS),
    "audit-writer": set(AUDIT_TOOLS),
}

DENIED: list[str] = []                    # every refusal, for the run report
AGENT_IDS: dict[str, str] = {}            # opaque agent_id -> agent name


async def remember_agent(payload, tool_use_id: str | None, ctx: HookContext):
    """A subagent's `agent_id` is an opaque hash, not its name.  SubagentStart
    is where the CLI tells you which is which, so the gate below can look the
    caller up instead of guessing."""
    AGENT_IDS[payload["agent_id"]] = payload["agent_type"]
    return {}


def agent_key(agent_id: str | None) -> str:
    """The router is the only caller with no agent id of its own."""
    if not agent_id:
        return ROUTER
    return AGENT_IDS.get(agent_id, f"unknown:{agent_id}")


async def gate(tool_name: str, tool_input: dict, ctx: ToolPermissionContext):
    """Every tool call in the run passes through here first.

    A caller we cannot identify gets nothing: the dict has no entry, the set
    is empty, and the call is denied.  Failing closed is the whole point --
    an unrecognised agent is not a reason to hand out the audit writer.
    """
    who = agent_key(ctx.agent_id)
    if tool_name in TOOL_BOUNDARY.get(who, set()):
        return PermissionResultAllow(updated_input=tool_input)
    DENIED.append(f"{who} -> {tool_name}")
    return PermissionResultDeny(
        message=f"{who} has no {tool_name}. Its allow-list is "
                f"{sorted(TOOL_BOUNDARY.get(who, set())) or 'empty'}.")


# ---- 6. THE ROUTER ------------------------------------------------------

options = ClaudeAgentOptions(
    model=MODEL,
    fallback_model=MODEL,
    # The ROLE, the DATE, and the boundary the router itself lives inside.
    system_prompt=(
        "You are a concise access-desk agent coordinating three specialists. "
        "For every access request: delegate to employee-identity to resolve "
        "who is asking, then to entitlement-reader for the policy on the "
        "resource, then to audit-writer EXACTLY ONCE to record the request. "
        "Record the request even when it cannot be satisfied -- an unknown "
        "person, an unknown resource or a refusal is still a request that "
        "must appear in the audit log. Never end without a ticket. "
        "Do the file work only through the Agent tool; you have no data tools "
        "and no audit tool of your own. "
        f"Today's date is {TODAY}. Use it, and only it, for anything dated.\n\n"
        "You cannot grant access. Nobody on this desk can -- there is no "
        "granting tool anywhere in this system. The desk decides who OWNS the "
        "request and records that, and provisioning happens elsewhere.\n\n"
        "You do not decide the decision_owner either. It is computed in Python "
        "from entitlement_policy.json when the ticket is written. Never "
        "announce a decision_owner before the ticket comes back; report the "
        "ticket you are given.\n\n"
        "Self-service (an employee resetting their OWN password or unlocking "
        "their OWN account), Finance-Admins membership, any admin-role grant, "
        "and a request to speak with a manager are all handled the same way "
        "as any other resource request: delegate, then audit-writer records "
        "it and Python decides.\n\n"
        "This desk has no connection to any real identity or account system: "
        "even a self-service ticket whose decision_owner comes back \"Agent\" "
        "is a LOCAL SIMULATION, not a real password reset or account unlock. "
        "Never tell a requester their password now works, that they can log "
        "in, or that their account is unlocked -- say the request was "
        "approved and simulated, nothing more. For decision_owner \"Human\", "
        "say the request is pending a human; never say access was granted."),
    agents=SUBAGENTS,
    mcp_servers={"desk": DESK},
    cwd=HERE,
    # ONE GLOBAL CATALOGUE.  `tools` and `disallowed_tools` here are the
    # SESSION's tool list, not the router's: narrow it to delegation and the
    # subagents lose the desk too.  So it lists everything anyone needs, and
    # WHO may call WHAT is settled one line down, in Python, by gate().
    tools=[*DELEGATE_TOOLS, *ALL_DESK_TOOLS],
    # Deliberately empty.  Nothing is pre-approved, so every tool call --
    # including every one the router tries itself -- goes through gate().
    allowed_tools=[],
    can_use_tool=gate,
    hooks={"SubagentStart": [HookMatcher(hooks=[remember_agent])]},
    env={"CLAUDE_CODE_MAX_OUTPUT_TOKENS": str(MAX_OUTPUT_TOKENS)},
    max_turns=MAX_TURNS,
)

# ---- 7. THE RUN: one `async for`, and no loop of ours -------------------
# The SDK owns the agent loop: it sends the prompt, sees the model ask for a
# tool, runs it, feeds the result back, and goes round again.  Everything
# below only READS what that loop produced.

async def one_message(request: str):
    """can_use_tool only runs in STREAMING mode, so the prompt goes in as an
    async iterable rather than a string. One message, then the stream ends --
    the difference is the gate in section 5 actually getting asked."""
    yield {"type": "user", "message": {"role": "user", "content": request}}


async def run_desk(request: str) -> dict:
    print(f"\n{'=' * 66}\nREQUEST: {request}\n{'=' * 66}")
    CURRENT_CASE.clear()
    CURRENT_CASE["request"] = request
    DENIED.clear()
    delegations, write_calls, model_reply, verdict = 0, 0, "", None

    async for msg in query(prompt=one_message(request), options=options):
        if isinstance(msg, ResultMessage):
            verdict = msg          # nested ones too; the LAST is the whole run
        elif isinstance(msg, AssistantMessage):
            # parent_tool_use_id is None only for the router itself.
            from_router = getattr(msg, "parent_tool_use_id", None) is None
            for block in msg.content:
                if isinstance(block, TextBlock) and block.text.strip():
                    if from_router:
                        model_reply = block.text    # what the router SAID
                elif isinstance(block, ToolUseBlock):
                    if block.name in DELEGATE_TOOLS:
                        delegations += 1
                    elif block.name in AUDIT_TOOLS:
                        write_calls += 1

    # The agent's turn is over. Everything from here is ordinary Python
    # acting on what got persisted -- not on what the agent said happened.
    written = CURRENT_CASE.get("ticket") or backstop(request)

    # Re-fetch by ticket_id from audit.jsonl rather than trusting the
    # in-process object: this is the same lookup a separate notifier
    # process would have to do, and it is what verify_persisted_ticket
    # already promised is on disk.
    ticket = get_ticket_by_id(written["ticket_id"]) or written

    # The ticket is resolved BEFORE the reply is decided, because what the
    # requester is told depends on it -- not on how the router phrased
    # things.  See reply_for() just below: for a Human ticket the presented
    # reply is authored in Python, not taken from model_reply.
    print(f"\n{reply_for(ticket, model_reply)}\n")
    print(f"delegations: {delegations}   audit calls: {write_calls}   "
          f"ticket: {ticket['ticket_id']}")
    if DENIED:
        print(f"blocked by the tool boundary: {', '.join(DENIED)}")
    if verdict:
        print(f"terminal_reason: {verdict.terminal_reason}   "
              f"cost: ${verdict.total_cost_usd or 0:.4f}")
        if verdict.terminal_reason != "completed":
            print("WARNING: this run did NOT succeed -- investigate.")
    who_owns_it(ticket)

    # Notification is not a tool: no agent chose to call this, and no agent
    # could have skipped it. It runs here, after the loop, decided solely by
    # ticket["decision_owner"] as read back from disk.
    if ticket["decision_owner"] == OWNER_HUMAN:
        notify_human_approver(ticket)

    return ticket          # ticket_id + full record


def backstop(request: str) -> dict:
    """EXACTLY ONE ticket per completed request -- including the ones the
    router walked away from.

    The first run of this file lost a request: employee-identity reported
    not_found, the router explained itself politely to the user, and nothing
    reached audit.jsonl.  A prompt saying "always file a ticket" would have
    made that rarer, not impossible.  This makes it impossible: the run is
    not over until a ticket exists, and Python writes the one the desk owes.

    It re-reads the request text rather than trusting anything the model
    said.  Whatever it cannot identify stays unidentified, and decide_owner()
    sends an unidentified request to a person.
    """
    print(f"{BOLD}NO TICKET FROM THE DESK{OFF} -- the backstop is filing one.")
    person = resolve_employee(request)
    resource = next((r for r in POLICY["resources"] if r in request.lower()),
                    "unidentified")
    return record_ticket(
        person["employee_id"] if person else "unidentified",
        resource, normalize_action(request),
        agent_note="filed by the Python backstop: the run ended with no "
                   "ticket from audit-writer")


# =========================================================================
#  8.  >>>>>>>>  T H E   H U M A N - I N - T H E - L O O P  <<<<<<<<
# =========================================================================
# THIS IS THE LINE THE WHOLE DAY IS ABOUT.  Everything above answered the
# request; this says who OWNS it -- and it was decided in PYTHON, by
# decide_owner(), from entitlement_policy.json, before the ticket hit disk:
#
#   Agent   the policy resolved it: the resource, the department, the role
#           and the action all lined up, or the person already had it
#   Human   the policy did NOT resolve it.  The agent still replied, but the
#           DECISION was never its own to make
#
# The notification itself is in notify_human_approver(), called from
# run_desk() AFTER the agent's turn is over -- not a tool, so no agent
# decides whether it fires or gets to skip it. It only ever fires for a
# Human ticket, and only ever prints itself as sent once the POST actually
# got a 2xx back.

BLUE, BOLD, OFF = "\033[94m", "\033[1m", "\033[0m"

# A model reply that says "access granted" about a Human-owned ticket is the
# one sentence this desk can never let stand -- it is the sentence a
# requester actually acts on.  Scanned for below, purely so a violation is
# visible; it changes nothing, because reply_for() never uses model_reply
# for a Human ticket in the first place.
GRANT_CLAIM = re.compile(r"\b(granted|approved|access (is|has been) (given|"
                         r"enabled)|you (now )?have access)\b", re.I)


def reply_for(ticket: dict, model_reply: str) -> str:
    """The reply actually shown for this request.

    For a Human ticket this is authored HERE, in Python, from the ticket --
    not taken from whatever the router said.  "Must say pending, must not
    say granted" is worth nothing as a sentence in a system prompt if a
    confused or rushed router can still write "you're all set" over it; it
    is worth something once the text the requester reads is built from
    ticket["decision_owner"] and nothing else.
    """
    if ticket["decision_owner"] == OWNER_HUMAN:
        if GRANT_CLAIM.search(model_reply or ""):
            print(f"{BOLD}NOTE{OFF} -- the router's own reply claimed access "
                  f"was granted on a Human-owned ticket; overriding it below.")
        return (f"Ticket {ticket['ticket_id']} has been recorded. This request "
                f"requires human approval and is now PENDING -- no access, "
                f"reset or unlock has been granted. A person will decide: "
                f"{ticket['reason']}")

    base = model_reply or (f"Ticket {ticket['ticket_id']} has been recorded "
                           f"and completed by the agent: {ticket['reason']}")

    # A self-service ticket is a SIMULATION (see simulate_self_service): the
    # first live run of this had the router tell the requester "you should
    # now be able to log in with your new credentials", which is exactly
    # the claim nothing in this file is allowed to make. The disclaimer is
    # appended here, in Python, so it is on the reply regardless of how the
    # router phrased its own summary.
    if POLICY["resources"].get(ticket["resource"], {}).get("self_service_only"):
        base += ("\n\n[Local simulation only -- no real account, password or "
                 "permission was actually changed.]")
    return base


def who_owns_it(ticket: dict | None) -> None:
    if not ticket:
        # Every completed request is meant to end in exactly one ticket,
        # including the dull ones.  A request with no ticket is one nobody
        # can audit.
        print(f"{BOLD}NO TICKET{OFF} -- nothing recorded, nothing to audit.")
        return

    if ticket["decision_owner"] == OWNER_HUMAN:          # <<< THE HANDOFF >>>
        print(f"\n{BLUE}{BOLD}{'=' * 66}\n"
              f"  HUMAN-IN-THE-LOOP -- this request is now a PERSON'S\n"
              f"{'=' * 66}{OFF}")
        print(f"{BLUE}  ticket     {ticket['ticket_id']}\n"
              f"  requester  {ticket['requester']}\n"
              f"  resource   {ticket['resource']}\n"
              f"  action     {ticket['action']}\n"
              f"  a person must decide because:  {ticket['reason']}\n"
              f"  (notify_human_approver() runs next -- see [notify] below){OFF}\n")
    else:
        print(f"\nOWNED BY THE AGENT -- the policy covered it. "
              f"Ticket {ticket['ticket_id']}: {ticket['reason']}\n")


# ---- 9. TRY IT ----------------------------------------------------------
# Same code, different requests, and the TICKET says who owned each outcome.


async def main() -> None:
    # Support asking to read CRM reports -> policy auto-approves -> Agent.
    await run_desk("Tomas Alvarez needs read access to crm-reports.")
    # High sensitivity, requires_human_approval -> Human.
    await run_desk("Mei Lin is asking for read access to payroll-ledger.")
    # Self-service, resource own-password/action reset -> Agent, simulated.
    await run_desk("employee-001 wants to reset their own password.")
    # Finance-Admins is always requires_human_approval -> Human, regardless
    # of how the request is worded or what's already held.
    await run_desk("employee-002 would like to join Finance-Admins.")
    # Intern on a role that deploy-staging denies -> Human.
    # await run_desk("Grace Bello wants deploy access to deploy-staging.")
    # Nobody by that name in the directory -> Human.
    # await run_desk("Jordan Fisher needs read access to crm-reports.")
    # Self-service claimed for someone ELSE's account -> Human.
    # await run_desk("employee-001 wants to reset employee-002's password.")
    # Any admin-role grant is unconditional -> Human.
    # await run_desk("Daniel Okafor wants admin access to prod-database.")
    # Manager-escalation phrasing is unconditional -> Human.
    # await run_desk("employee-001 wants to speak to their manager about a raise.")


if __name__ == "__main__":
    asyncio.run(main())
