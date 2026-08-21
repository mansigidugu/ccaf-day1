import os
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

ticket = """
My internet has been completely down since this morning.
I have an important work meeting in one hour and need the connection restored urgently.
"""

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
                }
            },
            "required": [
                "category",
                "priority",
                "summary"
            ],
            "additionalProperties": False
        }
    }
]

response = client.messages.create(
    model="claude-sonnet-5",
    max_tokens=300,
    tools=tools,
    tool_choice={
        "type": "tool",
        "name": "save_triage"
    },
    messages=[
        {
            "role": "user",
            "content": ticket
        }
    ]
)

for block in response.content:
    if block.type == "tool_use":
        print(block.input)