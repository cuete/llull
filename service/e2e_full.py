"""Full e2e: ingest source -> analyze -> verify graph nodes + document exist."""
import urllib.request
import urllib.parse
import json
import time

BASE = "http://localhost:8000"
TOPIC_ID = "0e71f9af-23df-460b-ac9a-6f3356c23020"
HEADERS = {"X-User-Id": "test-user-local"}

def get(path):
    req = urllib.request.Request(f"{BASE}{path}", headers=HEADERS)
    return json.loads(urllib.request.urlopen(req).read())

def post_form(path, fields):
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers={
        **HEADERS, "Content-Type": "application/x-www-form-urlencoded"
    })
    return json.loads(urllib.request.urlopen(req).read())

def post_json(path, body=None):
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers={
        **HEADERS, "Content-Type": "application/json"
    })
    return json.loads(urllib.request.urlopen(req).read())

# 0. Clean slate
sources = get(f"/topics/{TOPIC_ID}/sources")
for s in sources:
    req = urllib.request.Request(f"{BASE}/topics/{TOPIC_ID}/sources/{s['id']}", headers=HEADERS, method="DELETE")
    urllib.request.urlopen(req)
print(f"[0] Cleaned {len(sources)} sources")

# 1. Ingest URL source
print("[1] Ingesting URL source...")
resp = post_form(f"/topics/{TOPIC_ID}/sources", {
    "source_type": "url",
    "name": "Python asyncio docs",
    "content": "https://docs.python.org/3/library/asyncio.html"
})
task_id = resp["task_id"]

# Poll until done
for i in range(40):
    time.sleep(2)
    task = get(f"/tasks/{task_id}")
    print(f"    [{i*2}s] status={task['status']} progress={task['progress']}")
    if task['status'] == 'done':
        source_id = json.loads(task['result'])['source_id']
        print(f"    Source ready: {source_id}")
        break
    elif task['status'] == 'failed':
        print(f"FAIL: ingest failed: {task['error']}")
        exit(1)
else:
    print("FAIL: ingest timeout")
    exit(1)

# 2. Check graph before analysis
graph_before = get(f"/topics/{TOPIC_ID}/graph")
print(f"[2] Graph before analyze: {len(graph_before['nodes'])} nodes, {len(graph_before['edges'])} edges")

# 3. Call POST /analyze and consume SSE stream
print("[3] Calling POST /analyze (SSE stream)...")
req = urllib.request.Request(
    f"{BASE}/topics/{TOPIC_ID}/analyze",
    data=b"",
    headers={**HEADERS, "Content-Type": "application/json"},
    method="POST"
)
events = []
with urllib.request.urlopen(req, timeout=120) as res:
    buf = ""
    event_type = None
    for raw in res:
        line = raw.decode("utf-8").rstrip("\n")
        if line.startswith("event:"):
            event_type = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data_str = line.split(":", 1)[1].strip()
            try:
                data = json.loads(data_str)
            except Exception:
                data = data_str
            events.append((event_type, data))
            print(f"    SSE {event_type}: {str(data)[:120]}")
        elif line == "":
            event_type = None

print(f"    Total SSE events: {len(events)}")

# 4. Check graph after analysis
graph_after = get(f"/topics/{TOPIC_ID}/graph")
print(f"[4] Graph after analyze: {len(graph_after['nodes'])} nodes, {len(graph_after['edges'])} edges")
for n in graph_after['nodes'][:5]:
    print(f"    node: {n['label']} ({n['status']})")

# 5. Check document
doc = get(f"/topics/{TOPIC_ID}/document")
print(f"[5] Document: {len(doc.get('blocks', []))} blocks")
if doc.get('blocks'):
    print(f"    First block preview: {doc['blocks'][0]['content_md'][:200]}")

# 6. Final assertions
errors = []
if len(graph_after['nodes']) == 0:
    errors.append("FAIL: no graph nodes after analyze")
if len(doc.get('blocks', [])) == 0:
    errors.append("FAIL: no document blocks after analyze")
error_events = [e for e in events if e[0] == 'error']
if error_events:
    errors.append(f"FAIL: SSE errors: {error_events}")

if errors:
    for e in errors:
        print(e)
    print("\nRESULT: FAIL")
else:
    print(f"\nRESULT: PASS - {len(graph_after['nodes'])} nodes, {len(graph_after['edges'])} edges, {len(doc['blocks'])} doc blocks")
