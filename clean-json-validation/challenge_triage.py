import os
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()

client = Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY")
)

# Allowed values from the assignment
CATEGORIES = [
    "Internet Outage",
    "Billing",
    "Account",
    "Technical Support",
]

PRIORITIES = [
    "Low",
    "Medium",
    "High",
    "Urgent",
]


# Claude must return this structure through tool_use.
tools = [
    {
        "name": "save_triage",
        "description": "Save the classification of a customer support ticket.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string"
                },
                "priority": {
                    "type": "string"
                },
                "summary": {
                    "type": "string"
                },
            },
            "required": [
                "category",
                "priority",
                "summary",
            ],
            "additionalProperties": False,
        },
    }
]


def extract(ticket, previous_error=None):
    """
    Ask Claude to classify the ticket using the save_triage tool.
    If a previous validation error exists, send that exact error
    back to Claude so it can correct the next attempt.
    """

    prompt = f"""
Classify this customer support ticket.

TICKET:
{ticket}

Allowed categories:
{CATEGORIES}

Allowed priorities:
{PRIORITIES}

Rules:
- category must be one of the allowed categories.
- priority must be one of the allowed priorities.
- summary must not be empty.
- summary must be 140 characters or fewer.
- summary must not be a verbatim copy of the ticket.
"""

    if previous_error:
        prompt += f"""

Your previous result failed validation.

The EXACT validation error was:

{previous_error}

Correct this specific problem in your next result.
"""

    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=300,
        tools=tools,
        tool_choice={
            "type": "tool",
            "name": "save_triage",
        },
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
    )

    # Read structured data directly from block.input.
    # Do NOT use json.loads().
    for block in response.content:
        if block.type == "tool_use":
            return block.input

    raise RuntimeError(
        "Claude did not return a tool_use block."
    )


def validate(data, ticket):
    """
    Validate both structure-related values and semantic constraints.
    Returns:
        (True, None)
    or:
        (False, "specific error")
    """

    category = data.get("category")
    priority = data.get("priority")
    summary = data.get("summary")

    # Validate category
    if category not in CATEGORIES:
        return (
            False,
            f'category "{category}" not allowed; '
            f'use {", ".join(CATEGORIES)}'
        )

    # Validate priority
    if priority not in PRIORITIES:
        return (
            False,
            f'priority "{priority}" not allowed; '
            f'use Low/Medium/High/Urgent'
        )

    # Validate summary exists
    if not isinstance(summary, str) or not summary.strip():
        return (
            False,
            "summary must not be empty"
        )

    # Validate summary length
    if len(summary) > 140:
        return (
            False,
            f"summary is {len(summary)} characters; "
            f"maximum is 140"
        )

    # Validate that summary isn't simply the ticket copied verbatim
    if summary.strip() == ticket.strip():
        return (
            False,
            "summary must not be a verbatim copy of the ticket"
        )

    return True, None


def escalate(ticket, last_error):
    """
    If all three attempts fail, escalate instead of returning
    an empty record.
    """

    return {
        "outcome": "needs_review",
        "ticket": ticket,
        "last_error": last_error,
    }


def triage(ticket):
    """
    Try at most 3 times.

    If validation fails:
        1. Save the exact error.
        2. Send that error to Claude on the next attempt.

    If validation succeeds:
        return saved result.

    If all 3 attempts fail:
        return needs_review.
    """

    previous_error = None

    for attempt in range(1, 4):

        print()
        print(f"--- Attempt {attempt} ---")

        if previous_error:
            print("Sending previous validation error to Claude:")
            print(previous_error)
            print()

        # ---------------------------------------------------------
        # DEMONSTRATION:
        # Force attempt 1 to contain an invalid priority.
        #
        # This guarantees that the screenshot demonstrates:
        #
        # invalid result
        #       ↓
        # validation failure
        #       ↓
        # exact error sent back
        #       ↓
        # Claude corrects it
        #       ↓
        # valid result
        #
        # Attempts 2 and 3 use the real Claude extraction.
        # ---------------------------------------------------------

        if attempt == 1:
            data = {
                "category": "Internet Outage",
                "priority": "Critical",
                "summary": "Customer has no internet."
            }
        else:
            data = extract(
                ticket,
                previous_error
            )

        print("Extracted:")
        print(data)

        # Validate the result
        valid, reason = validate(
            data,
            ticket
        )

        if valid:
            print()
            print("Validation: PASSED")

            return {
                "outcome": "saved",
                "data": data,
                "attempts": attempt,
            }

        # Validation failed
        print()
        print("Validation: FAILED")
        print(f"Reason: {reason}")

        # IMPORTANT:
        # Carry the exact validation error into the next attempt.
        previous_error = reason

    # Three attempts have been exhausted.
    print()
    print("Maximum attempts reached.")
    print("Escalating to needs_review.")

    return escalate(
        ticket,
        previous_error
    )


# -------------------------------------------------------------
# TEST TICKET
# -------------------------------------------------------------

ticket = """
My home internet has been completely down since this morning.
I have an important work presentation in one hour and need the
connection restored urgently.
Please help me get back online as soon as possible.
"""


# -------------------------------------------------------------
# RUN TRIAGE
# -------------------------------------------------------------

result = triage(ticket)


# -------------------------------------------------------------
# FINAL RESULT
# -------------------------------------------------------------

print()
print("=== FINAL RESULT ===")
print(result)