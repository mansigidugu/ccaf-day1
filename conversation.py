from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

client = Anthropic()

messages = []


def get_text(response):
    for block in response.content:
        if hasattr(block, "text"):
            return block.text
    return ""


# Turn 1
messages.append({
    "role": "user",
    "content": "What is the capital of France?"
})

r1 = client.messages.create(
    model="claude-sonnet-5",
    max_tokens=100,
    messages=messages
)

answer1 = get_text(r1)
print("Turn 1:", answer1)

# Add Claude's Turn 1 reply back into conversation history
messages.append({
    "role": "assistant",
    "content": answer1
})


# Turn 2
messages.append({
    "role": "user",
    "content": "What is its population?"
})

r2 = client.messages.create(
    model="claude-sonnet-5",
    max_tokens=100,
    messages=messages
)

answer2 = get_text(r2)
print("Turn 2:", answer2)

# Add Claude's Turn 2 reply back into conversation history
messages.append({
    "role": "assistant",
    "content": answer2
})


# Turn 3
messages.append({
    "role": "user",
    "content": "What famous landmark can I visit there?"
})

r3 = client.messages.create(
    model="claude-sonnet-5",
    max_tokens=100,
    messages=messages
)

answer3 = get_text(r3)
print("Turn 3:", answer3)
