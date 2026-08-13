from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

client = Anthropic()

response = client.messages.create(
    model="claude-sonnet-5",
    max_tokens=200,
    messages=[
        {
            "role": "user",
            "content": "Explain gravity simply."
        }
    ]
)

for block in response.content:
    if hasattr(block, "text"):
        print(block.text)

