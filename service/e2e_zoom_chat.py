"""E2E test: zoom a node then verify chat responds with valid markdown."""
import urllib.request
import json
import sys

BASE = "http://localhost:8000"
HEADERS = {"X-User-Id": "test-user-local"}


def get(path):
    req = urllib.request.Request(f"{BASE}{path}", headers=HEADERS)
    return json.loads(urllib.request.urlopen(req).read())


def post_stream_zoom(path):
    """Call zoom endpoint and collect SSE events; return list of (type, data) tuples."""
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=b"",
        headers={**HEADERS, "Content-Type": "application/json"},
        method="POST",
    )
    events = []
    event_type = None
    with urllib.request.urlopen(req, timeout=120) as res:
        for raw in res:
            line = raw.decode("utf-8").rstrip("\n")
            if line.startswith("event:"):
                event_type = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and event_type:
                data = json.loads(line.split(":", 1)[1].strip())
                events.append((event_type, data))
                if event_type == "done":
                    break
    return events


def post_json_stream_chat(path, body):
    """Send chat message and collect streamed tokens; return full response text."""
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        headers={**HEADERS, "Content-Type": "application/json"},
    )
    tokens = []
    event_type = None
    with urllib.request.urlopen(req, timeout=120) as res:
        for raw in res:
            line = raw.decode("utf-8").rstrip("\n")
            if line.startswith("event:"):
                event_type = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and event_type == "token":
                parsed = json.loads(line.split(":", 1)[1].strip())
                tokens.append(parsed.get("text", ""))
    return "".join(tokens)


def fail(msg):
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


# --- Step 1: Find a topic with unexplored nodes ---
topics = get("/topics")
assert isinstance(topics, list) and len(topics) > 0, "No topics available"

topic_id = None
graph_before = None
target_node = None

for t in topics:
    g = get(f"/topics/{t['id']}/graph")
    unexplored = [n for n in g["nodes"] if n["status"] == "unexplored"]
    if unexplored:
        topic_id = t["id"]
        graph_before = g
        target_node = unexplored[0]
        break

if not topic_id:
    fail("No topic with unexplored nodes found — run analysis first")

print(f"Topic: {topic_id}")
print(f"Zooming into: {target_node['label']}")

# --- Step 2: Zoom the node ---
zoom_events = post_stream_zoom(f"/topics/{topic_id}/zoom/{target_node['id']}")
done_event = next((e for e in zoom_events if e[0] == "done"), None)
if not done_event:
    fail(f"No done event from zoom. Got: {zoom_events}")

sub_nodes_count = done_event[1].get("sub_nodes", 0)
print(f"Sub-nodes created: {sub_nodes_count}")
if sub_nodes_count == 0:
    fail("Zoom returned 0 sub-nodes")

# --- Step 3: Verify graph grew ---
graph_after = get(f"/topics/{topic_id}/graph")
if len(graph_after["nodes"]) <= len(graph_before["nodes"]):
    fail(f"Graph didn't grow: {len(graph_before['nodes'])} -> {len(graph_after['nodes'])} nodes")
print(f"Graph grew: {len(graph_before['nodes'])} -> {len(graph_after['nodes'])} nodes")

# --- Step 4: Send zoom auto-chat message ---
node_label = target_node["label"]
chat_message = (
    f'Zoomed into "{node_label}". Analyze the sub-concepts discovered and explain how they relate '
    f"to each other and to the parent concept. Use bullet points, plain markdown only."
)
print(f"Sending chat: {chat_message[:80]}...")

response_text = post_json_stream_chat(f"/topics/{topic_id}/chat", {"message": chat_message})
print(f"Response length: {len(response_text)} chars")
print(f"Preview: {response_text[:300]}")

# --- Step 5: Validate response ---
if len(response_text) < 50:
    fail(f"Chat response too short ({len(response_text)} chars): {response_text!r}")

# Check it's not raw JSON (should be markdown)
stripped = response_text.strip()
if stripped.startswith("{") or stripped.startswith("["):
    fail(f"Response looks like JSON, not markdown: {stripped[:100]}")

# Should contain at least one markdown indicator (bullet or heading)
has_markdown = any(c in response_text for c in ["-", "*", "#", "\n"])
if not has_markdown:
    fail("Response has no markdown indicators")

print("PASS")
