"""Validate connectivity to Baseten's hackathon inference endpoint."""

import os

from dotenv import load_dotenv
from openai import OpenAI


def test_baseten_connection():
    """Send a test request to the Baseten-hosted Muse Spark Open model."""
    load_dotenv()

    api_key = os.getenv("BASETEN_API_KEY")
    if not api_key:
        raise ValueError("BASETEN_API_KEY is not configured.")

    client = OpenAI(
        base_url="https://inference.baseten.co/v1",
        api_key=api_key,
        timeout=30.0,
    )

    response = client.chat.completions.create(
        model="meta-models/muse-spark-open-1026",
        messages=[
            {
                "role": "user",
                "content": "Reply with exactly: MAVIS Baseten connection successful.",
            }
        ],
    )

    print(response.choices[0].message.content)


if __name__ == "__main__":
    test_baseten_connection()