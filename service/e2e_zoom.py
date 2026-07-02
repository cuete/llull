"""E2E test for zoom endpoint and graph growth verification."""
import urllib.request
import json

BASE = "http://localhost:8000"
TOPIC_ID = "0e71f9af-23df-460b-ac9a-6f3356c23020"
HEADERS = {"X-User-Id": "test-user-local"}


def get(path):
    req = urllib.request.Request(f"{BASE}{path}", headers=HEADERS)
    return json.loads(urllib.request.urlopen(req).read())


def post_stream(path):
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


# Get graph
graph = get(f"/topics/{TOPIC_ID}/graph")
unexplored = [n for n in graph["nodes"] if n["status"] == "unexplored"]
assert unexplored, "No unexplored nodes to zoom"
target = unexplored[0]
print(f"Zooming into: {target['label']}")

# Zoom
events = post_stream(f"/topics/{TOPIC_ID}/zoom/{target['id']}")
done = next((e for e in events if e[0] == "done"), None)
assert done, f"No done event. Got: {events}"
sub_nodes = done[1].get("sub_nodes", 0)
print(f"Sub-nodes created: {sub_nodes}")
assert sub_nodes > 0, "No sub-nodes created"

# Verify in graph
graph2 = get(f"/topics/{TOPIC_ID}/graph")
assert len(graph2["nodes"]) > len(graph["nodes"]), "Graph didn't grow after zoom"
print(f"Graph grew: {len(graph['nodes'])} -> {len(graph2['nodes'])} nodes")
print("RESULT: PASS")
