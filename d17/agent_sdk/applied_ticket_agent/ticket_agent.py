import asyncio
import json
import os

from claude_agent_sdk import (
    ClaudeAgentOptions,
    create_sdk_mcp_server,
    query,
    tool,
)

from claude_agent_sdk.types import (
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
)


HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = "claude-haiku-4-5-20251001"


# Fake ticket data for this practice assignment.
TICKETS = {
    "T-101": {
        "status": "In progress",
        "owner": "Maya",
        "priority": "High",
    },
    "T-102": {
        "status": "Waiting for customer",
        "owner": "Jordan",
        "priority": "Medium",
    },
    "T-103": {
        "status": "Resolved",
        "owner": "Priya",
        "priority": "Low",
    },
}


@tool(
    "get_ticket_status",
    "Look up the status, owner, and priority of a support ticket using its ticket ID.",
    {"ticket_id": str},
)
async def get_ticket_status(args: dict) -> dict:
    ticket_id = args["ticket_id"].strip().upper()
    ticket = TICKETS.get(ticket_id)

    if ticket is None:
        result = {
            "error": "ticket not found",
            "ticket_id": ticket_id,
        }
    else:
        result = {
            "ticket_id": ticket_id,
            **ticket,
        }

    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(result),
            }
        ]
    }


ticket_server = create_sdk_mcp_server(
    name="tickets",
    version="1.0.0",
    tools=[get_ticket_status],
)


options = ClaudeAgentOptions(
    model=MODEL,
    fallback_model=MODEL,
    system_prompt="You are a concise internal ticket-support agent.",
    mcp_servers={"tickets": ticket_server},
    cwd=HERE,
    setting_sources=["project"],
    skills=["ticket-support"],
    allowed_tools=[
        "mcp__tickets__get_ticket_status",
        "Skill",
    ],
    permission_mode="dontAsk",
    max_turns=8,
)


async def main() -> None:
    question = input("Ask about a ticket: ")

    async for message in query(prompt=question, options=options):
        if isinstance(message, SystemMessage) and message.subtype == "init":
            skills = (message.data or {}).get("skills", [])
            loaded = "ticket-support" in skills
            print(f"Skill 'ticket-support' loaded: {loaded}")

        elif isinstance(message, AssistantMessage):
            for block in message.content or []:
                if isinstance(block, ToolUseBlock):
                    print(f"[tool] {block.name}: {block.input}")

                elif isinstance(block, TextBlock) and block.text.strip():
                    print(f"Claude: {block.text}")

        elif isinstance(message, ResultMessage):
            print(f"terminal_reason: {message.terminal_reason}")


if __name__ == "__main__":
    asyncio.run(main())