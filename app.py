from flask import Flask, request, redirect, send_from_directory, make_response, jsonify
import os
import json
import uuid
import hashlib
from datetime import datetime
import sys

# Ensure backend can be imported
sys.path.append(os.path.join(os.path.dirname(__file__), "backend"))

try:
    from backend.text_responder import generate_text_reply
    from backend.json_generator import generate_design_json
    from backend.image_generator import generate_image, generate_image_from_prompt
except ImportError:
    # Fallback or mock if backend is missing dependencies
    print("Warning: Backend modules not found or failed to import.")
    def generate_text_reply(text): return "Backend not connected."
    def generate_design_json(text): return {}
    def generate_image(json): return "https://via.placeholder.com/1024"

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
USERS_FILE = os.path.join(DATA_DIR, "users.json")
DEVICES_FILE = os.path.join(DATA_DIR, "devices.json")
CHAT_HISTORY_FILE = os.path.join(DATA_DIR, "chat_history.json")


def ensure_storage():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(USERS_FILE):
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump({"users": []}, f, indent=2)
    if not os.path.exists(DEVICES_FILE):
        with open(DEVICES_FILE, "w", encoding="utf-8") as f:
            json.dump({"devices": []}, f, indent=2)


def load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def find_user_by_email(email: str):
    if not email:
        return None
    email_norm = email.strip().lower()
    data = load_json(USERS_FILE)
    for user in data.get("users", []):
        if user.get("email", "").strip().lower() == email_norm:
            return user
    return None


def add_user(email: str, password: str, username: str = None, first: str = None, last: str = None, age: str = None, role: str = None):
    user_id = str(uuid.uuid4())
    user_record = {
        "user_id": user_id,
        "email": email.strip().lower(),
        "password_hash": hash_password(password),
        "created_at": datetime.utcnow().isoformat() + "Z",
        "username": username or "",
        "first": first or "",
        "last": last or "",
        "age": age or None,
        "role": role or None,
    }
    data = load_json(USERS_FILE)
    data.setdefault("users", [])
    data["users"].append(user_record)
    save_json(USERS_FILE, data)
    return user_record


def add_device_for_user(user_id: str) -> str:
    device_id = str(uuid.uuid4())
    entry = {
        "device_id": device_id,
        "user_id": user_id,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    data = load_json(DEVICES_FILE)
    data.setdefault("devices", [])
    data["devices"].append(entry)
    save_json(DEVICES_FILE, data)
    return device_id


def find_device_for_cookie(user_id: str, device_id: str) -> bool:
    data = load_json(DEVICES_FILE)
    for d in data.get("devices", []):
        if d.get("device_id") == device_id and d.get("user_id") == user_id:
            return True
    return False


def auto_login_user_from_cookies(req) -> str | None:
    user_id = req.cookies.get("user_id")
    device_id = req.cookies.get("device_id")
    if not user_id or not device_id:
        return None
    if not os.path.exists(DEVICES_FILE):
        return None
    if find_device_for_cookie(user_id, device_id):
        return user_id
    return None

# New: API endpoint for device check for JS auto-login
def get_cookie(name):
    return request.cookies.get(name)

@app.route("/check_device", methods=["POST"])
def check_device():
    ensure_storage()
    data = request.get_json(force=True, silent=True) or {}
    # Try from body first, fallback to cookies
    user_id = data.get("user_id") or get_cookie("user_id")
    device_id = data.get("device_id") or get_cookie("device_id")
    valid = False
    if user_id and device_id and find_device_for_cookie(user_id, device_id):
        valid = True
    return jsonify({"valid": valid})

@app.route("/")
def index():
    # On start, open loading page
    return send_from_directory(BASE_DIR, "loading.html")

@app.route("/signup", methods=["GET", "POST"])
def signup():
    ensure_storage()
    # Auto-login check
    if request.method == "GET":
        auto_user = auto_login_user_from_cookies(request)
        if auto_user:
            # Redirect to chat if already logged in
            return redirect("/chat.html")
        return send_from_directory(BASE_DIR, "signup.html")

    # POST: create new user
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    username = request.form.get("username", "").strip() or None
    first = request.form.get("first", "").strip() or None
    last = request.form.get("last", "").strip() or None
    age = request.form.get("age", "").strip() or None
    role = request.form.get("role", "").strip() or None

    if not email or not password:
        return redirect("/signup")
    existing = find_user_by_email(email)
    if existing:
        # Simple collision handling
        return "User already exists. Try logging in.", 400
    user = add_user(email, password, username=username, first=first, last=last, age=age, role=role)
    # After signup, redirect to login to authenticate
    return redirect("/login")

@app.route("/login", methods=["GET", "POST"])
def login():
    ensure_storage()
    if request.method == "GET":
        # If user already logged in via cookies and device mapping exists, auto-login
        auto_user_id = auto_login_user_from_cookies(request)
        if auto_user_id:
            return redirect("/chat.html")
        return send_from_directory(BASE_DIR, "login.html")

    # POST: authenticate
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    if not email or not password:
        return redirect("/login")

    user = find_user_by_email(email)
    if not user:
        return "Invalid email or password", 401
    if user.get("password_hash") != hash_password(password):
        return "Invalid email or password", 401

    user_id = user["user_id"]
    # Create device for this login and store in devices.json
    device_id = add_device_for_user(user_id)
    resp = redirect("/chat.html")
    # Save cookies: user_id and device_id
    resp.set_cookie("user_id", user_id, max_age=60 * 60 * 24 * 365)  # 1 year
    resp.set_cookie("device_id", device_id, max_age=60 * 60 * 24 * 365)
    return resp

@app.route("/settings")
def settings():
    # Simple access guard
    ensure_storage()
    user_id = auto_login_user_from_cookies(request)
    if not user_id:
        # Not logged in, redirect to login
        return redirect("/login")
    # Serve the existing settings page
    return send_from_directory(BASE_DIR, "settings.html")

@app.route("/home")
@app.route("/home.html")
def home():
    """
    Serve the home page. This fixes 404s when requesting /home or /home.html.
    """
    ensure_storage()
    return send_from_directory(BASE_DIR, "home.html")

# Catch-all for serving other .html files placed in the project root.
# This should come after specific routes so they win first.
@app.route("/<path:filename>")
def serve_html_file(filename: str):
    """
    Serve any existing .html file from the project root.
    - Only serves files ending with .html
    - Returns `error.html` (404) if requested file doesn't exist and `error.html` is present
    - Basic safety: reject path traversal attempts
    """
    ensure_storage()
    # Basic safety checks
    if filename.startswith("/") or ".." in filename:
        return "Invalid request", 400
    if not filename.lower().endswith(".html"):
        # For non-html, let the app return 404
        return "Not Found", 404

    target_path = os.path.join(BASE_DIR, filename)
    if os.path.exists(target_path) and os.path.isfile(target_path):
        return send_from_directory(BASE_DIR, filename)

    # Fallback to error.html if present
    error_path = os.path.join(BASE_DIR, "error.html")
    if os.path.exists(error_path):
        return send_from_directory(BASE_DIR, "error.html"), 404
    return "Not Found", 404


# --- Chat Endpoints ---

def load_chat_history():
    if not os.path.exists(CHAT_HISTORY_FILE):
        return []
    try:
        return load_json(CHAT_HISTORY_FILE)
    except:
        return []

def save_chat_history(history):
    save_json(CHAT_HISTORY_FILE, history)

@app.route("/chat_messages")
def chat_messages():
    ensure_storage()
    user_id = auto_login_user_from_cookies(request)
    # For demo purposes, if not logged in, maybe show empty or error?
    # The user might want to test without full login flow, but let's stick to auth.
    if not user_id:
        return jsonify([]) 
    
    all_history = load_chat_history()
    # Filter for this user
    user_history = [m for m in all_history if m.get('user_id') == user_id]
    return jsonify(user_history)

@app.route("/send_message", methods=["POST"])
def send_message():
    ensure_storage()
    user_id = auto_login_user_from_cookies(request)
    if not user_id:
        # If testing without login, maybe generate a temp ID?
        # But let's enforce login for "proper" app.
        return "Unauthorized", 401
        
    text = request.form.get("text", "")
    # Handle image upload if any (future feature, for now just text input)
    
    if not text:
        return "No text provided", 400

    # Save user message
    msg_id = str(uuid.uuid4())
    user_msg = {
        "id": msg_id,
        "user_id": user_id,
        "role": "user",
        "text": text,
        "time": datetime.utcnow().isoformat() + "Z"
    }
    
    history = load_chat_history()
    history.append(user_msg)
    save_chat_history(history)
    
    # Generate response
    # Simple intent classification
    intent_keywords = ["design", "plan", "layout", "image", "picture", "photo", "interior", "room"]
    
    bot_text = ""
    bot_images = []  # Changed from single bot_image to list
    
    try:
        if any(k in text.lower() for k in intent_keywords):
            # Generate Design JSON
            json_str = generate_design_json(text)
            
            # Parse JSON to understand requirements
            try:
                # Clean up json string if needed (sometimes LLM returns markdown code blocks)
                clean_json = json_str.replace("```json", "").replace("```", "").strip()
                design_data = json.loads(clean_json)
            except:
                design_data = {}

            style = design_data.get("style", "modern")
            rooms = design_data.get("rooms", [])
            if not rooms:
                rooms = ["Living Room", "Kitchen", "Bedroom"] # Default if none parsed

            # 1. Outer House 3D Structure
            exterior_prompt = f"Professional 3D architectural visualization of a {style} house exterior, photorealistic 8k render, cinematic lighting, architectural photography, detailed textures, landscaped garden, blue sky, wide angle shot"
            try:
                url = generate_image_from_prompt(exterior_prompt)
                bot_images.append(url)
            except Exception as e:
                print(f"Error generating exterior: {e}")

            # 2. 2D Floor Plan
            plan_prompt = f"High quality 2D architectural floor plan of a {style} house, top down view, technical drawing, blueprint style on white background, clear room labels, wall measurements, dimensions in meters and feet, furniture layout, precise lines, high resolution"
            try:
                url = generate_image_from_prompt(plan_prompt)
                bot_images.append(url)
            except Exception as e:
                print(f"Error generating plan: {e}")

            # 3. Rooms
            for room in rooms:
                room_prompt = f"Professional interior design photography of a {style} {room}, award winning interior design, 8k resolution, photorealistic, perfect lighting, detailed furniture, high end finishes, architectural digest style"
                try:
                    url = generate_image_from_prompt(room_prompt)
                    bot_images.append(url)
                except Exception as e:
                    print(f"Error generating {room}: {e}")

            bot_text = f"Here is the complete design suite for your {style} house, including exterior, floor plan, and room designs."
        else:
            # Generate Text
            bot_text = generate_text_reply(text)
    except Exception as e:
        bot_text = f"Error processing request: {str(e)}"
        print(f"Backend Error: {e}")

    bot_msg = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "role": "bot",
        "text": bot_text,
        "image_urls": bot_images, # Send list
        "time": datetime.utcnow().isoformat() + "Z"
    }
            
    history.append(bot_msg)
    save_chat_history(history)
    
    return jsonify({"status": "ok"})

@app.route("/clear_chat", methods=["POST"])
def clear_chat():
    ensure_storage()
    user_id = auto_login_user_from_cookies(request)
    if not user_id:
        return "Unauthorized", 401
    
    all_history = load_chat_history()
    # Keep messages that are NOT from this user
    new_history = [m for m in all_history if m.get('user_id') != user_id]
    save_chat_history(new_history)
    
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    ensure_storage()
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)

