from intent_classifier import classify_intent
from json_generator import generate_design_json
from image_generator import generate_image
from text_responder import generate_text_reply

def main():
    user_input = input("Enter your prompt: ")

    intent = classify_intent(user_input)
    print("Intent Detected:", intent)

    if intent in [
        "interior_design",
        "house_plan",
        "floor_plan_2d",
        "exterior_design"
    ]:
        json_data = generate_design_json(user_input)
        print("Design JSON saved.")

        image_url = generate_image(json_data)
        print("Generated Image URL:", image_url)

    else:
        reply = generate_text_reply(user_input)
        print("Response:", reply)

if __name__ == '__main__':
    main()
