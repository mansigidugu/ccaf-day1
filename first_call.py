from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

client = Anthropic()

response = client.messages.create(
    model="claude-sonnet-5",
    max_tokens=100,
    messages=[
        {
            "role": "user",
            "content": "Explain machine learning in two simple sentences."
        }
    ]
)

print(response.content[0].text)
