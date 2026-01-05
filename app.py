import os
import json
import threading
import time
import webbrowser
from functools import wraps
from flask import Flask, request, jsonify, session, redirect, url_for, send_file, make_response
from werkzeug.security import generate_password_hash, check_password_hash
import requests
# Embedded OpenRouter API key (provided by user)
# WARNING: this stores a secret in source. Remove before sharing the repo.
OPENROUTER_API_KEY = "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"

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

app = Flask(__name__, static_folder=None)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key-change-me")


@app.route("/user.json", methods=["GET", "POST"])
def users_json():
    """
    - GET: returns JSON array of users
    - POST: accepts a full JSON array and overwrites the users file
    This matches the frontend expectations from the provided HTML.
    """
    if request.method == "GET":
        users = read_users()
        return jsonify(users)
    # POST
    try:
        payload = request.get_json(force=True)
        if not isinstance(payload, list):
            return jsonify({"error": "expected a JSON array"}), 400
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
    new_id = data.get("id") or f"uid_{os.urandom(6).hex()}"
    hashed = generate_password_hash(data["password"])
    user = {
        "id": new_id,
        "username": data.get("username"),
        "email": email,
        "first": data.get("first"),
        "last": data.get("last", ""),
        "password": hashed,
        "age": data.get("age"),
        "role": data.get("role")
    }
    users.append(user)
    write_users(users)
    session["user_id"] = new_id
    return jsonify({"ok": True, "user": {"id": new_id, "username": user["username"], "email": email}})


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

    stored_pw = user.get("password", "")
    password_ok = False
    # Support both hashed and legacy-plaintext passwords
    if stored_pw.startswith("pbkdf2:") or stored_pw.startswith("sha256$") or stored_pw.startswith("argon2"):
        password_ok = check_password_hash(stored_pw, password)
    else:
        # legacy plaintext (front-end created) — accept and migrate to hashed
        if stored_pw == password:
            password_ok = True
            user["password"] = generate_password_hash(password)
            # persist migration
            users = read_users()
            for i, uu in enumerate(users):
                if uu.get("email") == email:
                    users[i] = user
                    break
            write_users(users)

    if not password_ok:
        return jsonify({"error": "invalid credentials"}), 401

    session["user_id"] = user.get("id") or user.get("email")
    return jsonify({"ok": True, "user": {"id": session["user_id"], "username": user.get("username"), "email": user.get("email")}})


@app.route("/api/session", methods=["GET"])
def api_session():
    uid = session.get("user_id")
    if not uid:
        return jsonify({"user": None})
    users = read_users()
    u = next((x for x in users if x.get("id") == uid or x.get("email") == uid), None)
    if not u:
        return jsonify({"user": None})
    return jsonify({"user": {"id": u.get("id"), "username": u.get("username") or u.get("first"), "email": u.get("email")}})


@app.route("/logout", methods=["GET"])
def logout():
    session.pop("user_id", None)
    return redirect("/login.html")


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """
    Proxy endpoint to call the external model API.
    Accepts JSON: { "message": "user text", "api_key": "(optional override)" }
    Prefers OPENAI_API_KEY env var, then api_key in request body (for quick testing),
    then file 'api_key.txt' in project root.
    """
    payload = request.get_json(force=True) or {}
    message = payload.get("message") or ""
    if not message:
        return jsonify({"error": "missing message"}), 400

    # Resolve API key: env var -> embedded key -> api_key.txt (do NOT accept client-sent api_key)
    api_key = os.environ.get("OPENAI_API_KEY") or OPENROUTER_API_KEY
    key_file = os.path.join(BASE_DIR, "api_key.txt")
    if not api_key and os.path.exists(key_file):
        try:
            with open(key_file, "r", encoding="utf-8") as f:
                api_key = f.read().strip()
        except Exception:
            api_key = None
    if not api_key:
        return jsonify({"error": "no API key configured. Set OPENAI_API_KEY or create api_key.txt"}), 500

    model = payload.get("model") or "openai/gpt-oss-120b:free"

    # Use OpenRouter chat completions endpoint first
    try:
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        chat_body = {
            "model": model,
            "messages": [{"role": "user", "content": message}],
            "max_tokens": 800
        }
        r = requests.post("https://api.openrouter.ai/v1/chat/completions", headers=headers, json=chat_body, timeout=30)
        if r.ok:
            try:
                j = r.json()
            except Exception:
                # not JSON, return raw text
                return jsonify({"ok": True, "response": r.text})
            text = None
            if "choices" in j and len(j["choices"]) > 0:
                ch = j["choices"][0]
                if "message" in ch and isinstance(ch["message"].get("content"), str):
                    text = ch["message"]["content"]
                elif "text" in ch:
                    text = ch["text"]
            if text is not None:
                return jsonify({"ok": True, "response": text})
        else:
            # include status and body for debugging
            try:
                body = r.text
            except Exception:
                body = "<no body>"
            # try to continue to fallback, but record reason
            first_error_info = {"status_code": r.status_code, "body": body}
    except Exception as e:
        first_error_info = {"exception": str(e)}

    # Fallback to Responses API
    try:
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        resp_body = {"model": model, "input": message}
        r2 = requests.post("https://api.openrouter.ai/v1/responses", headers=headers, json=resp_body, timeout=30)
        if not r2.ok:
            return jsonify({"error": "model API error", "status_code": r2.status_code, "body": r2.text}), 502
        try:
            j2 = r2.json()
        except Exception:
            return jsonify({"ok": True, "response": r2.text})
        # Try a few common places for the generated text
        text = None
        if "output" in j2 and isinstance(j2["output"], list) and len(j2["output"])>0:
            # output may contain dicts with 'content' array
            first = j2["output"][0]
            if isinstance(first, dict):
                if "content" in first and isinstance(first["content"], list) and len(first["content"])>0:
                    # content items may be dicts with 'text' or strings
                    c0 = first["content"][0]
                    if isinstance(c0, dict) and "text" in c0:
                        text = c0["text"]
                    elif isinstance(c0, str):
                        text = c0
        if not text:
            # Try choices / output_text
            if "choices" in j2 and len(j2["choices"])>0:
                ch = j2["choices"][0]
                if isinstance(ch.get("message"), dict):
                    # some responses include message.content as array or string
                    content = ch["message"].get("content")
                    if isinstance(content, str):
                        text = content
                    elif isinstance(content, list) and len(content)>0:
                        firstc = content[0]
                        if isinstance(firstc, dict) and "text" in firstc:
                            text = firstc["text"]
                elif ch.get("text"):
                    text = ch.get("text")
            if not text and j2.get("output_text"):
                text = j2.get("output_text")
        if not text:
            # As last resort, return full JSON
            return jsonify({"ok": True, "response": j2})
        return jsonify({"ok": True, "response": text})
    except Exception as e:
        return jsonify({"error": "request failed", "detail": str(e)}), 500


def _serve_static_file(filename):
    path = os.path.join(BASE_DIR, filename)
    if not os.path.exists(path):
        return "Not found", 404
    return send_file(path)


@app.route("/chat")
@login_required
def chat():
    """
    Serve chat.html but inject a small script with the current user's name
    so client-side UI can read window.currentUser without relying on storage.
    """
    uid = session.get("user_id")
    user = None
    if uid:
        users = read_users()
        user = next((x for x in users if x.get("id") == uid or x.get("email") == uid), None)
    chat_path = os.path.join(BASE_DIR, "chat.html")
    if not os.path.exists(chat_path):
        return "chat.html not found", 404
    with open(chat_path, "r", encoding="utf-8") as f:
        content = f.read()
    inject = ""
    if user:
        name = user.get("first") or user.get("username") or user.get("email")
        inject = f'<script>window.currentUser = {{name: {json.dumps(name)}}};</script>'
    # Inject before closing </body>
    if "</body>" in content:
        content = content.replace("</body>", inject + "\n</body>")
    return make_response(content)


@app.route("/<path:filename>", methods=["GET"])
def any_file(filename):
    # serve static html/css/js assets directly from project root
    return _serve_static_file(filename)


@app.route("/", methods=["GET"])
def index():
    return redirect("/home.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # Open the default browser to home.html shortly after the server starts.
    def _open_browser():
        time.sleep(0.6)
        try:
            webbrowser.open(f"http://127.0.0.1:{port}/home.html")
        except Exception:
            pass
    threading.Thread(target=_open_browser, daemon=True).start()
    # use_reloader=False prevents double browser opens when debug=True
    app.run(host="0.0.0.0", port=port, debug=True, use_reloader=False)

 
