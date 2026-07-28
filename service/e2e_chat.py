"""E2E test: verify chat SSE stream receives token events and returns a response."""
import urllib.request
import urllib.parse
import json
import time

BASE = "http://localhost:8000"
TOPIC_ID = "0e71f9af-23df-460b-ac9a-6f3356c23020"
HEADERS = {"X-User-Id": "test-user-local"}


def post_json_stream(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        headers={**HEADERS, "Content-Type": "application/json"},
    )
    tokens = []
    event_type = None
    with urllib.request.urlopen(req, timeout=60) as res:
        for raw in res:
            line = raw.decode("utf-8").rstrip("\n")
            if line.startswith("event:"):
                event_type = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and event_type == "token":
                data_str = line.split(":", 1)[1].strip()
                parsed = json.loads(data_str)
                tokens.append(parsed.get("text", ""))
    return "".join(tokens)


response = post_json_stream(f"/topics/{TOPIC_ID}/chat", {"message": "What is asyncio?"})
print(f"Response length: {len(response)} chars")
print(f"Preview: {response[:200]}")
assert len(response) > 50, f"FAIL: response too short: {response}"
print("PASS: chat response received")
