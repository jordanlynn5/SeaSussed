"""Response time benchmark for the SeaSussed /analyze endpoint.

Usage:
    uv run python -m scripts.benchmark                        # local (port 8000)
    uv run python -m scripts.benchmark https://your-url.run.app

Requires a running backend server with Vertex AI credentials.
Fixture: tests/fixtures/wholeFoods_sockeye.png  (optional — uses stub if absent)

Output: p50, p90, max latency in ms. Exits non-zero if p90 exceeds 3000ms.
"""

import base64
import json
import statistics
import sys
import time
import urllib.request
from pathlib import Path

BACKEND_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
FIXTURE = Path(__file__).parent.parent / "tests" / "fixtures" / "wholeFoods_sockeye.png"

# Use real fixture if available; otherwise a tiny 1×1 white PNG stub.
if FIXTURE.exists():
    screenshot_b64 = base64.b64encode(FIXTURE.read_bytes()).decode()
else:
    # 1×1 white PNG — backend will fall back to no_seafood, but latency is valid.
    _stub = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?"
        b"\x00\x05\xfe\x02\xfe\xdc\xccY\xe7\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    screenshot_b64 = base64.b64encode(_stub).decode()
    print("WARNING: fixture not found — using 1×1 stub PNG (latency still valid)")

payload = json.dumps(
    {
        "screenshot": screenshot_b64,
        "url": "https://www.wholefoodsmarket.com/product/sockeye-salmon",
        "page_title": "Wild Alaskan Sockeye Salmon",
        "related_products": [],
    }
).encode()

N = 5
times: list[float] = []
print(f"Benchmarking {BACKEND_URL}/analyze with {N} requests…")
for i in range(N):
    start = time.time()
    req = urllib.request.Request(
        f"{BACKEND_URL}/analyze",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            resp.read()
    except Exception as e:
        print(f"  [{i + 1}/{N}] ERROR: {e}")
        sys.exit(1)
    elapsed = (time.time() - start) * 1000
    times.append(elapsed)
    print(f"  [{i + 1}/{N}] {elapsed:.0f}ms")

p50 = statistics.median(times)
p90 = sorted(times)[int(N * 0.9)]
print(f"\np50: {p50:.0f}ms")
print(f"p90: {p90:.0f}ms")
print(f"max: {max(times):.0f}ms")

if p90 < 3000:
    print("PASS — p90 < 3000ms")
else:
    print("FAIL — p90 exceeds 3000ms target")
    sys.exit(1)
