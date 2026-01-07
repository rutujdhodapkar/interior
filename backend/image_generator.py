import os
from config import client

def generate_image(json_data):
    prompt = f"""
Using the following JSON, generate a clean architectural image.

{json_data}

Image type: 2D floor plan or interior design
Top view, white background, labeled rooms
"""

    image = client.images.generate(
        model="provider-4/sdxl-lite",
        prompt=prompt,
        size="1024x1024"
    )

    image_url = image.data[0].url

    os.makedirs("output", exist_ok=True)

    with open("output/image_url.txt", "w") as f:
        f.write(image_url)

    return image_url

def generate_image_from_prompt(prompt_text):
    image = client.images.generate(
        model="provider-4/sdxl-lite",
        prompt=prompt_text,
        size="1024x1024"
    )
    return image.data[0].url
