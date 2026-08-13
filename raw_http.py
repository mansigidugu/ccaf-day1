import requests
import os
from dotenv import load_dotenv

load_dotenv()

response = requests.post(
    "https://api.anthropic.com/v1/messages",
    headers={
        "content-type": "application/json",
        "x-api-key": os.environ["ANTHROPIC_API_KEY"],
        "anthropic-version": "2023-06-01"
    },
    json={
        "model": "claude-sonnet-5",
        "max_tokens": 200,
        "messages": [
            {
                "role": "user",
                "content": "Explain gravity simply."
            }
        ]
    }
)

data = response.json()

for block in data["content"]:
    if block.get("type") == "text":
        print(block["text"])
