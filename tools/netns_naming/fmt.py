import sys, json
raw = sys.stdin.read()
i = raw.rfind("[")
code, body = raw[i:], raw[:i]
try:
    j = json.loads(body)
    if isinstance(j, dict) and "outcomes" in j:
        parts = []
        for o in j["outcomes"]:
            s = f'{o.get("interface")}@{o.get("namespace") or "root"}={o.get("status")}'
            if o.get("detail"):
                s += ":" + o["detail"][:90]
            parts.append(s)
        body = " ".join(parts)
    elif isinstance(j, dict):
        body = json.dumps({k: v for k, v in j.items() if k in ("detail", "message", "status", "id")})[:200]
except Exception:
    body = body[:200]
print("   ", code, body)
