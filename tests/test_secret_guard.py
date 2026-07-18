"""S0: secret-guard hook — Bash commands that would print secrets get blocked (exit 2)."""
import json
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).parent.parent / ".claude" / "hooks" / "secret_guard.py"


def run_hook(command: str) -> subprocess.CompletedProcess:
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    return subprocess.run(
        [sys.executable, str(HOOK)], input=payload, capture_output=True, text=True
    )


def test_blocks_printing_env_file():
    for cmd in ["cat .env", "less ../.env", "head -5 .env", "bat /Users/x/proj/.env"]:
        r = run_hook(cmd)
        assert r.returncode == 2, f"should block: {cmd}"


def test_blocks_echoing_key_vars():
    for cmd in ["echo $OPENAI_API_KEY", "printenv SERPER_API_KEY", "echo ${SUPABASE_SERVICE_ROLE_KEY}"]:
        r = run_hook(cmd)
        assert r.returncode == 2, f"should block: {cmd}"


def test_allows_normal_commands():
    for cmd in ["ls -la", "pytest tests/", "python gtm/schema.py", "grep -c KEY .env.example", "source .venv/bin/activate"]:
        r = run_hook(cmd)
        assert r.returncode == 0, f"should allow: {cmd} -> {r.stderr}"


def test_allows_dotenv_loading_in_python():
    # loading vars into a process is fine; printing them is not
    r = run_hook("python -c 'from dotenv import load_dotenv; load_dotenv()'")
    assert r.returncode == 0
