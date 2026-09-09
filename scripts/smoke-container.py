"""Exercise the production image against a disposable database; no cloud calls."""

import json
import os
import re
import sys
import tempfile
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE = os.getenv("SMOKE_BASE_URL", "http://127.0.0.1:8000")
ORIGIN = "https://sound.example.com"
STATE_FILE = Path(tempfile.gettempdir()) / "signal-slate-container-smoke.json"


def request(path, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = Request(
        BASE + path,
        data=data,
        headers={"Origin": ORIGIN, "Content-Type": "application/json", **(headers or {})},
    )
    try:
        response = urlopen(req, timeout=30)
    except HTTPError as error:
        response = error
    with response:
        return response.status, response.headers, response.read()


def main():
    if "--restore-only" in sys.argv:
        saved = json.loads(STATE_FILE.read_text())
        status, _, payload = request(saved["path"], headers=saved["headers"])
        assert status == 200
        assert json.loads(payload)["state"] == "PREVIEW_COMPLETE"
        print("Saved rehearsal survived container restart.")
        STATE_FILE.unlink()
        return

    assert request("/ready")[0] == 200
    for path in ("/", "/rehearsal", "/rehearsal/example", "/reports/example"):
        status, headers, payload = request(path)
        assert status == 200, path
        assert "text/html" in headers["Content-Type"]
        assert headers["Cache-Control"] == "no-cache"
        assert b"root" in payload
    html = request("/")[2].decode()
    assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', html)
    assert assets
    audio_paths = []
    for path in assets:
        status, headers, payload = request(path)
        assert status == 200
        assert "immutable" in headers["Cache-Control"]
        audio_paths.extend(re.findall(r"/assets/[^\s\"\x27]+\.wav", payload.decode()))
    assert audio_paths, "Bundled dialogue must be referenced by the frontend"
    status, headers, payload = request(audio_paths[0], headers={"Range": "bytes=0-3"})
    assert status == 206 and payload == b"RIFF"
    for path in ("/api/missing", "/assets/missing.js", "/.env", "/README.md"):
        assert request(path)[0] == 404, path
    assert request("/api/sessions", {"mode": "live"})[0] == 503
    assert request("/api/sessions", {}, {"Origin": "https://evil.invalid"})[0] == 403

    status, headers, payload = request("/api/sessions", {"mode": "preview"})
    assert status == 201
    cookie = SimpleCookie()
    cookie.load(headers["Set-Cookie"])
    assert cookie["ss_cap"]["secure"] and cookie["ss_cap"]["httponly"]
    state = json.loads(payload)
    session_path = f"/api/sessions/{state['id']}"
    # The test talks HTTP directly to the container behind the HTTPS proxy boundary.
    owned = {"Cookie": f"ss_cap={cookie['ss_cap'].value}", "X-CSRF-Token": state["csrf_token"]}
    assert request(session_path)[0] == 404

    def step(operation, extra=None):
        nonlocal state
        code, _, content = request(
            session_path + "/" + operation,
            {"revision": state["revision"], **(extra or {})},
            owned,
        )
        assert code == 200, operation
        state = json.loads(content)
        assert state.get("error") is None, operation

    step("baseline")
    assert len(state["baseline"]["samples"]) == 484
    step("investigate")
    step("constraints", {"text": "Exclude channel 11"})
    constraints = [value | {"confirmed": True} for value in state["interpretation"]["constraints"]]
    step("confirm", {"constraints": constraints})
    plan = state["candidate_plans"][0]
    approval = {
        key: plan[key]
        for key in (
            "plan_id",
            "plan_version",
            "action_hash",
            "constraints_hash",
            "base_config_hash",
        )
    }
    step("approve", {"approval": approval | {"approved": True}})
    step("apply")
    assert state["state"] == "PREVIEW_COMPLETE"
    assert state["verification"]["terminal_status"] == "INCONCLUSIVE"
    assert len(state["comparison"]["samples"]) == 484
    STATE_FILE.touch(mode=0o600, exist_ok=True)
    STATE_FILE.write_text(json.dumps({"path": session_path, "headers": owned}))
    print("Pages, assets, audio seeking, origin protection, HTTPS cookies and full preview passed.")


if __name__ == "__main__":
    main()
