"""Verify the auto-starter message content — what does the bot send first?"""
import urllib.request, json

BASE = "http://localhost:8000"
TOPIC_ID = "0e71f9af-23df-460b-ac9a-6f3356c23020"
HEADERS = {"X-User-Id": "test-user-local"}

def get(path):
    req = urllib.request.Request(f"{BASE}{path}", headers=HEADERS)
    return json.loads(urllib.request.urlopen(req).read())

def delete(path):
    req = urllib.request.Request(f"{BASE}{path}", headers=HEADERS, method="DELETE")
    urllib.request.urlopen(req)

def post_stream(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers={
        **HEADERS, "Content-Type": "application/json"
    })
    tokens = []
    event_type = None
    with urllib.request.urlopen(req, timeout=90) as res:
        for raw in res:
            line = raw.decode("utf-8").rstrip("\n")
            if line.startswith("event:"):
                event_type = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_str = line.split(":", 1)[1].strip()
                try:
                    parsed = json.loads(data_str)
                    if event_type == "token":
                        tokens.append(parsed.get("text", ""))
                except Exception:
                    pass
    return "".join(tokens)

# Step 1: wipe chat history
history = get(f"/topics/{TOPIC_ID}/chat")
print(f"Existing history: {len(history)} messages")
# Note: no DELETE endpoint for chat — need to check

# Step 2: check graph exists
graph = get(f"/topics/{TOPIC_ID}/graph")
print(f"Graph: {len(graph['nodes'])} nodes")

# Step 3: send the exact starter message the frontend sends
starter_msg = "List the key themes from the analyzed sources as a numbered markdown list. For each theme, write one sentence description. After the list, include the mermaid chart. Plain markdown only — no JSON, no code blocks except the mermaid chart."

print(f"\nSending starter message...")
response = post_stream(f"/topics/{TOPIC_ID}/chat", {"message": starter_msg})

print(f"\n=== FULL RESPONSE ({len(response)} chars) ===")
print(response)
print("=== END ===")

# Check for JSON
import re
json_pattern = re.search(r'\{["\s]*\w+["\s]*:', response)
if json_pattern:
    print(f"\nFAIL: response contains JSON at pos {json_pattern.start()}")
else:
    print("\nOK: no raw JSON detected")

# Check for mermaid
if "```mermaid" in response:
    print("OK: mermaid block present")
else:
    print("FAIL: no mermaid block in response")
