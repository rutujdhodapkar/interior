import os
from dotenv import load_dotenv
load_dotenv()
import requests
import json
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import requests.exceptions

def get_api_key(payload=None, allow_client_override=False):
    """
    Resolve API key with order:
      1. OPENAI_API_KEY env var
      2. OPENROUTER_API_KEY env var
      3. api_key.txt file in project root
      4. payload['api_key'] if allow_client_override is True
    """
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
    key_file = os.path.join(os.path.dirname(__file__), "api_key.txt")
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

def client_override_allowed(app_debug=False):
    """
    Allow client-sent api_key when running in debug mode or when
    ALLOW_CLIENT_API_KEY=1 is set in env.
    """
    return bool(os.environ.get("ALLOW_CLIENT_API_KEY") == "1" or app_debug)


def call_openrouter(message, model=None, max_tokens=800, timeout=30):
    """
    Send a chat/completion request to OpenRouter using the API key resolved
    by `get_api_key`. Returns a tuple (result_dict, http_status).

    The `result_dict` is JSON-serializable and mirrors the structure used by
    the rest of the app (e.g. {"ok": True, "response": "..."} or {"error": "..."}).
    """
    api_key = get_api_key(payload=None, allow_client_override=False)
    if not api_key:
        return ({"error": "API key not configured on server. Set OPENROUTER_API_KEY in .env or create api_key.txt"}, 500)

    # force the Xiaomi MIMO model explicitly
    model = "xiaomi/mimo-v2-flash:free"

    base_candidates = [
        os.environ.get("OPENROUTER_BASE_URL", "https://api.openrouter.ai").rstrip("/"),
        "https://gateway.openrouter.ai",
        "https://openrouter.ai"
    ]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://localhost",
        "Content-Type": "application/json"
    }

    session = requests.Session()
    https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    http_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    proxies = {}
    if https_proxy:
        proxies["https"] = https_proxy
    if http_proxy:
        proxies["http"] = http_proxy
    if proxies:
        session.proxies.update(proxies)

    retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 502, 503, 504], allowed_methods=["POST"])
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    chat_payload = {
        "model": model,
        "messages": [{"role": "user", "content": message}],
        "max_tokens": max_tokens
    }

    last_exc = None
    first_attempt_info = None
    for host in base_candidates:
        # Try chat/completions first
        chat_url = host.rstrip("/") + "/v1/chat/completions"
        try:
            try:
                print(f"[api_chat] trying endpoint: {chat_url}")
            except Exception:
                pass
            resp = session.post(chat_url, headers=headers, json=chat_payload, timeout=timeout)
            if resp and resp.ok:
                body_text = resp.text or ""
                content_type = resp.headers.get("Content-Type", "")
                is_html = content_type.startswith("text/html") or body_text.lstrip().startswith("<!DOCTYPE")
                if not is_html:
                    try:
                        j = resp.json()
                    except Exception:
                        return ({"ok": True, "response": body_text}, 200)
                    if "choices" in j and len(j["choices"]) > 0:
                        ch = j["choices"][0]
                        if "message" in ch and isinstance(ch["message"].get("content"), str):
                            return ({"ok": True, "response": ch["message"]["content"]}, 200)
                        elif ch.get("text"):
                            return ({"ok": True, "response": ch.get("text")}, 200)
                    return ({"ok": True, "response": j}, 200)
                # if HTML, fall through to try /v1/responses on same host
            else:
                if resp is not None and first_attempt_info is None:
                    first_attempt_info = {"url": chat_url, "status": resp.status_code, "body": resp.text[:300]}
        except requests.exceptions.RequestException as e:
            last_exc = e
            

        # Try Responses API as a fallback on the same host
        try:
            responses_url = host.rstrip("/") + "/v1/responses"
            try:
                print(f"[api_chat] trying endpoint: {responses_url}")
            except Exception:
                pass
            resp2 = session.post(responses_url, headers=headers, json={"model": model, "input": message}, timeout=timeout)
            if resp2 and resp2.ok:
                body_text = resp2.text or ""
                content_type = resp2.headers.get("Content-Type", "")
                is_html = content_type.startswith("text/html") or body_text.lstrip().startswith("<!DOCTYPE")
                if not is_html:
                    try:
                        data = resp2.json()
                    except Exception:
                        return ({"ok": True, "response": body_text}, 200)
                    # Try common response shapes
                    text = data.get("output_text") or data.get("output", None)
                    if text is None and isinstance(data.get("output"), list) and len(data["output"]) > 0:
                        first = data["output"][0]
                        if isinstance(first, dict) and "content" in first and isinstance(first["content"], list) and len(first["content"])>0:
                            c0v = first["content"][0]
                            if isinstance(c0v, dict) and "text" in c0v:
                                text = c0v["text"]
                            elif isinstance(c0v, str):
                                text = c0v
                    if isinstance(text, list):
                        text = " ".join([str(x) for x in text])
                    if text is not None:
                        return ({"ok": True, "response": text}, 200)
                    return ({"ok": True, "response": data}, 200)
                else:
                    if first_attempt_info is None:
                        first_attempt_info = {"url": responses_url, "status": resp2.status_code, "body": resp2.text[:300]}
            else:
                if resp2 is not None and first_attempt_info is None:
                    first_attempt_info = {"url": responses_url, "status": resp2.status_code, "body": resp2.text[:300]}
        except requests.exceptions.RequestException as e:
            last_exc = e
            continue

    msg = str(last_exc) if last_exc else "no response"
    hint = ""
    if "Failed to resolve" in msg or "NameResolutionError" in msg or "getaddrinfo" in msg:
        hint = "DNS resolution failed for api.openrouter.ai — try setting OPENROUTER_BASE_URL to gateway.openrouter.ai or set HTTPS_PROXY."
    return ({"error": "request failed", "detail": {"exception": msg, "hint": hint, "first_attempt": first_attempt_info}}, 500)


def stream_openrouter(message, model=None, timeout=60):
    """
    Generator that yields parsed stream chunks from OpenRouter's streaming API.
    Yields Python dicts for each JSON chunk; yields {'done': True} when stream completes;
    yields {'error': ...} on failures.
    """
    api_key = get_api_key(payload=None, allow_client_override=False)
    if not api_key:
        yield {"error": "API key not configured on server"}
        return

    # force model
    model = "xiaomi/mimo-v2-flash:free"

    base_candidates = [
        os.environ.get("OPENROUTER_BASE_URL", "https://api.openrouter.ai").rstrip("/"),
        "https://gateway.openrouter.ai",
        "https://openrouter.ai"
    ]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://localhost",
        "Content-Type": "application/json"
    }

    session = requests.Session()
    https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    http_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    proxies = {}
    if https_proxy:
        proxies["https"] = https_proxy
    if http_proxy:
        proxies["http"] = http_proxy
    if proxies:
        session.proxies.update(proxies)

    retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 502, 503, 504], allowed_methods=["POST"])
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    payload = {"model": model, "messages": [{"role": "user", "content": message}], "stream": True}

    for host in base_candidates:
        url = host.rstrip("/") + "/v1/chat/completions"
        try:
            try:
                print(f"[stream_openrouter] connecting to {url}")
            except Exception:
                pass
            resp = session.post(url, headers=headers, json=payload, stream=True, timeout=timeout)
            if not resp or not resp.ok:
                # try next host
                continue

            for raw_line in resp.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                line = raw_line.strip()
                if line.startswith("data:"):
                    line = line[len("data:"):].strip()
                if line == "[DONE]":
                    yield {"done": True}
                    return
                try:
                    chunk = json.loads(line)
                except Exception:
                    yield {"raw": line}
                    continue
                # If chunk has choices with delta content similar to JS SDK, yield content and usage when present
                yielded = False
                try:
                    if isinstance(chunk, dict) and "choices" in chunk and isinstance(chunk["choices"], list):
                        delta = chunk["choices"][0].get("delta", {})
                        content = delta.get("content")
                        if content:
                            yield {"content": content}
                            yielded = True
                    if isinstance(chunk, dict) and "usage" in chunk:
                        yield {"usage": chunk["usage"]}
                        yielded = True
                except Exception:
                    pass
                if not yielded:
                    yield chunk
            return
        except requests.exceptions.RequestException as e:
            continue
    yield {"error": "all_hosts_failed"}
