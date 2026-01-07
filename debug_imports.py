import sys
import os
import traceback

sys.path.append(os.path.join(os.path.dirname(__file__), "backend"))

try:
    print("Attempting to import backend modules...")
    from backend.text_responder import generate_text_reply
    print("Successfully imported text_responder")
    from backend.json_generator import generate_design_json
    print("Successfully imported json_generator")
    from backend.image_generator import generate_image
    print("Successfully imported image_generator")
except Exception:
    with open("error.log", "w") as f:
        traceback.print_exc(file=f)
    traceback.print_exc()
