import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(
    api_key="ddc-a4f-85189a80e6f448ae9667663046b621e5",
    base_url="https://api.a4f.co/v1"
)
