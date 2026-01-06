import os
import json
from functools import wraps
from flask import Flask, request, jsonify, session, redirect, send_file, Response
from werkzeug.security import generate_password_hash, check_password_hash
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_FILE = os.path.join(BASE_DIR, "user.json")

def read_users():
    if not os.path.exists(USERS_FILE):
        return []
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or []
    except Exception:
        return []

def write_users(users_list):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users_list, f, indent=2, ensure_ascii=False)

def find_user_by_email(email):
    users = read_users()
    for u in users:
        if u.get("email") == email:
            return u
    return None

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect("/login.html")
        return fn(*args, **kwargs)
    return wrapper

app = Flask(__name__, static_folder=BASE_DIR, static_url_path="")
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key-change-me")

def get_api_key(payload=None, allow_client_override=False):
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
    key_file = os.path.join(BASE_DIR, "api_key.txt")
    if not api_key and os.path.exists(key_file):
        try:
            with open(key_file, "r", encoding="utf-8") as f:
                api_key = f.read().strip()
        except Exception:
            api_key = None
    if not api_key and allow_client_override and payload:
        client_key = payload.get("api_key")
        if client_key:
            api_key = client_key.strip()
    return api_key


def call_openrouter(message, model=None, api_key=None, base_url=None, max_tokens=800, timeout=30):
    resolved_key = api_key or get_api_key(payload=None, allow_client_override=False)
    if not resolved_key:
        return ({"error": "API key not configured on server"}, 500)

    model = model or "xiaomi/mimo-v2-flash:free"
    bases = []
    if base_url:
        bases.append(base_url.rstrip("/"))
    env_base = os.environ.get("OPENROUTER_BASE_URL")
    if env_base:
        bases.append(env_base.rstrip("/"))
    bases.extend(["https://gateway.openrouter.ai", "https://api.openrouter.ai", "https://openrouter.ai"])

    headers = {
        "Authorization": f"Bearer {resolved_key}",
        "Content-Type": "application/json"
    }

    payload = {"model": model, "messages": [{"role": "user", "content": message}], "max_tokens": max_tokens}

    last_exc = None
    for base in bases:
        url = base + "/v1/chat/completions"
        try:
            try:
                print(f"[call_openrouter] trying {url}")
            except Exception:
                pass
            resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        except Exception as e:
            last_exc = e
            continue

        body_text = resp.text or ""
        if resp.status_code < 200 or resp.status_code >= 300:
            snippet = body_text[:1000]
            if resp.status_code in (401, 403):
                return ({"error": "authentication_failed", "status": resp.status_code, "body": snippet}, 401)
            last_exc = Exception(f"{resp.status_code}: {snippet}")
            continue

        try:
            j = resp.json()
        except Exception:
            return ({"ok": True, "response": body_text}, 200)

        if isinstance(j, dict) and "choices" in j and len(j["choices"]) > 0:
            ch = j["choices"][0]
            msg = ch.get("message", {}).get("content")
            if isinstance(msg, str):
                return ({"ok": True, "response": msg}, 200)
            txt = ch.get("text")
            if isinstance(txt, str):
                return ({"ok": True, "response": txt}, 200)
        return ({"ok": True, "response": j}, 200)

    return ({"error": "network_error", "exception": str(last_exc)}, 502)

@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        resp = app.make_default_options_response()
        headers = resp.headers
        headers["Access-Control-Allow-Origin"] = "*"
        headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
        headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
        return resp

@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return response

@app.route("/user.json", methods=["GET", "POST"])
def users_json():
    if request.method == "GET":
        return jsonify(read_users())

    try:
        payload = request.get_json(force=True)
        if not isinstance(payload, list):
            return jsonify({"error": "expected JSON array"}), 400
        write_users(payload)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/signup", methods=["POST"])
def api_signup():
    data = request.get_json(force=True)

    required = ["username", "email", "first", "password"]
    for k in required:
        if not data.get(k):
            return jsonify({"error": f"missing {k}"}), 400

    email = data["email"].strip().lower()

    if find_user_by_email(email):
        return jsonify({"error": "email already exists"}), 400

    users = read_users()

    new_id = f"uid_{os.urandom(6).hex()}"
    hashed_pw = generate_password_hash(data["password"])

    user = {
        "id": new_id,
        "username": data.get("username"),
        "email": email,
        "first": data.get("first"),
        "last": data.get("last", ""),
        "password": hashed_pw,
        "age": data.get("age"),
        "role": data.get("role")
    }

    users.append(user)
    write_users(users)

    session["user_id"] = new_id

    return jsonify({
        "ok": True,
        "user": {
            "id": new_id,
            "username": user["username"],
            "email": email
        }
    })

@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(force=True)

    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "missing credentials"}), 400

    user = find_user_by_email(email)

    if not user:
        return jsonify({"error": "user not found"}), 404

    if not check_password_hash(user["password"], password):
        return jsonify({"error": "invalid credentials"}), 401

    session["user_id"] = user["id"]

    return jsonify({
        "ok": True,
        "user": {
            "id": user["id"],
            "username": user.get("username"),
            "email": user["email"]
        }
    })

@app.route("/api/session", methods=["GET"])
def api_session():
    uid = session.get("user_id")

    if not uid:
        return jsonify({"user": None})

    user = next((u for u in read_users() if u["id"] == uid), None)

    if not user:
        return jsonify({"user": None})

    return jsonify({
        "user": {
            "id": user["id"],
            "username": user.get("username") or user.get("first"),
            "email": user["email"]
        }
    })

@app.route("/logout", methods=["GET"])
def logout():
    session.pop("user_id", None)
    return redirect("/login.html")

@app.route("/api/chat", methods=["POST"])
def api_chat():
    payload = request.get_json(force=True) or {}
    message = payload.get("message") or ""

    if not message:
        return jsonify({"error": "missing message"}), 400

    # Direct call using local helper
    model = payload.get("model") or None
    result, status = call_openrouter(message, model=model)
    return jsonify(result), status

@app.route("/api/stream", methods=["POST"])
def api_stream():
    # streaming endpoint removed
    return jsonify({"error": "streaming endpoint disabled"}), 404

def serve_html(filename):
    path = os.path.join(BASE_DIR, filename)
    if not os.path.exists(path):
        return "Not found", 404
    return send_file(path)

@app.route("/chat")
def chat():
    return serve_html("chat.html")

@app.route("/<path:filename>")
def static_proxy(filename):
    return serve_html(filename)

@app.route("/")
def index():
    return redirect("/home.html")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # Avoid Werkzeug reloader triggering SystemExit when running under a debugger.
    app.run(host="0.0.0.0", port=port, debug=True, use_reloader=False)
