from config import client

def generate_text_reply(user_input):
    response = client.chat.completions.create(
        model="provider-2/gpt-oss-120b",
        messages=[{"role": "user", "content": user_input}],
        temperature=0.7
    )

    return response.choices[0].message.content
