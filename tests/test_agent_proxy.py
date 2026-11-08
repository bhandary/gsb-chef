import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_agent_proxy_session_check():
    script = ROOT / "web/src/lib/agent-proxy-auth.test.mjs"
    result = subprocess.run(
        ["node", "--test", str(script)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_langgraph_proxy_route_calls_the_session_check():
    route = (ROOT / "web/src/app/api/[..._path]/route.ts").read_text()
    guard = (ROOT / "web/src/lib/agent-proxy-auth.mjs").read_text()
    callback = (ROOT / "web/src/app/api/auth/google/callback/route.ts").read_text()
    assert "authorizeAgentProxy" in route
    assert "passthrough.GET" in route
    assert "Sign in required." in guard
    assert "gsb_session" in guard
    assert "/auth/google/callback" in callback
    assert "SESSION_COOKIE" in callback
    assert "console.log" not in callback
    assert "console.log" not in route
