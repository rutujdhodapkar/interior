from config import client
import os

def generate_design_json(user_input):
    prompt = f"""
Convert the following architectural request into valid JSON.

User request:
"{user_input}"

JSON format:
{{
  "design_type": "",
  "rooms": [],
  "style": "",
  "view": "",
  "extra_details": ""
}}
"""

    response = client.chat.completions.create(
        model="provider-2/gpt-oss-120b",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )

    json_data = response.choices[0].message.content

    os.makedirs("output", exist_ok=True)

    with open("output/design.json", "w", encoding="utf-8") as f:
        f.write(json_data)

    return json_data
