import os
import streamlit as st
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

st.title("CCAF — Batch API Practice")

if "batch_id" not in st.session_state:
    st.session_state.batch_id = None


if st.button("See one request object"):
    request = {
        "custom_id": "prospect_001",
        "params": {
            "model": "claude-sonnet-5",
            "max_tokens": 300,
            "messages": [
                {
                    "role": "user",
                    "content": "Write a personalized onboarding email for Alice."
                }
            ],
        },
    }

    st.json(request)


if st.button("Submit batch"):

    requests = [
        {
            "custom_id": "prospect_001",
            "params": {
                "model": "claude-sonnet-5",
                "max_tokens": 300,
                "messages": [
                    {
                        "role": "user",
                        "content": "Write a personalized onboarding email for Alice."
                    }
                ],
            },
        },
        {
            "custom_id": "prospect_002",
            "params": {
                "model": "claude-sonnet-5",
                "max_tokens": 300,
                "messages": [
                    {
                        "role": "user",
                        "content": "Write a personalized onboarding email for Bob."
                    }
                ],
            },
        },
        {
            "custom_id": "prospect_003",
            "params": {
                "model": "claude-sonnet-5",
                "max_tokens": 300,
                "messages": [
                    {
                        "role": "user",
                        "content": "Write a personalized onboarding email for Charlie."
                    }
                ],
            },
        },
        {
            "custom_id": "prospect_004",
            "params": {
                "model": "claude-sonnet-5",
                "max_tokens": 300,
                "messages": [
                    {
                        "role": "user",
                        "content": "Write a personalized onboarding email for Diana."
                    }
                ],
            },
        },
        {
            "custom_id": "prospect_005",
            "params": {
                "model": "claude-sonnet-5",
                "max_tokens": 300,
                "messages": [
                    {
                        "role": "user",
                        "content": "Write a personalized onboarding email for Ethan."
                    }
                ],
            },
        },
    ]

    batch = client.messages.batches.create(requests=requests)

    st.session_state.batch_id = batch.id

    st.success(f"Batch submitted: {batch.id}")


if st.session_state.batch_id:

    st.subheader("Batch ID")
    st.code(st.session_state.batch_id)


    if st.button("Check status"):

        batch = client.messages.batches.retrieve(
            st.session_state.batch_id
        )

        st.write("Processing status:")
        st.write(batch.processing_status)

        st.write("Request counts:")

        st.json({
            "processing": batch.request_counts.processing,
            "succeeded": batch.request_counts.succeeded,
            "errored": batch.request_counts.errored,
            "canceled": batch.request_counts.canceled,
            "expired": batch.request_counts.expired,
        })


    if st.button("Collect results"):

        results = []

        for result in client.messages.batches.results(
            st.session_state.batch_id
        ):

            results.append({
                "custom_id": result.custom_id,
                "result_type": result.result.type,
            })

        st.write("Batch results:")
        st.json(results)