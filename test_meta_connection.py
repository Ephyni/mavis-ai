
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(
    base_url="https://api.meta.ai/v1",
    api_key=os.environ["MODEL_API_KEY"]
)

response = client.responses.create(
    model="muse-spark-1.3",
    input="Hello! My name is MAVIS. Introduce yourself in one sentence."
)

print(response.output_text)
