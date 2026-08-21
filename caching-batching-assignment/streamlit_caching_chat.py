import os
import streamlit as st
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

st.title("CCAF — Prompt Caching Practice")

model = st.sidebar.selectbox(
    "Model",
    ["claude-sonnet-5", "claude-haiku-4-5"]
)

caching = st.sidebar.checkbox("Prompt caching", value=True)

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.write(message["content"])

prompt = st.chat_input("Send a message")

if prompt:
    st.session_state.messages.append(
        {"role": "user", "content": prompt}
    )

    with st.chat_message("user"):
        st.write(prompt)

    system_content = [
        {
            "type": "text",
            "text": (
                "You are a helpful assistant for a CCAF caching exercise. "
                "Explain concepts clearly and concisely."
            ),
        }
    ]

    if caching:
        system_content[0]["cache_control"] = {"type": "ephemeral"}

    response = client.messages.create(
        model=model,
        max_tokens=500,
        system=system_content,
        messages=st.session_state.messages,
    )

    answer = next(

    block.text

    for block in response.content

    if hasattr(block, "text")

)

    st.session_state.messages.append(
        {"role": "assistant", "content": answer}
    )

    with st.chat_message("assistant"):
        st.write(answer)

    st.subheader("Usage")

    usage = response.usage

    st.write(
        {
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "cache_creation_input_tokens": getattr(
                usage, "cache_creation_input_tokens", 0
            ),
            "cache_read_input_tokens": getattr(
                usage, "cache_read_input_tokens", 0
            ),
        }
    )