#!/usr/bin/env python3
"""PreToolUse hook: block Bash commands that would print secrets into the transcript.

Blocks (exit 2): reading .env-style files, echoing/printing *KEY/TOKEN/SECRET* env vars.
Allows everything else (exit 0). Loading dotenv into a process is fine — printing is not.
"""
import json
import re
import sys

READ_CMDS = {"cat", "less", "more", "head", "tail", "bat", "strings", "nl", "vi", "vim", "open"}
SECRET_VAR = re.compile(r"\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)\w*\}?", re.I)
PRINT_CMD = re.compile(r"(?:^|[\s;|&(])(?:echo|printf)\b", re.I)
PRINTENV = re.compile(r"(?:^|[\s;|&(])printenv\s+\w*(KEY|TOKEN|SECRET|PASSWORD)\w*", re.I)


def is_blocked(command: str) -> str | None:
    tokens = command.split()
    cmds = {t for t in tokens}
    if cmds & READ_CMDS and any(t.rstrip("'\"").endswith(".env") for t in tokens):
        return "reading a .env file would print secrets into the transcript"
    if PRINT_CMD.search(command) and SECRET_VAR.search(command):
        return "echoing a secret env var would print it into the transcript"
    if PRINTENV.search(command):
        return "printenv on a secret var would print it into the transcript"
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # malformed input — do not break the harness
    if payload.get("tool_name") != "Bash":
        return 0
    command = (payload.get("tool_input") or {}).get("command", "")
    reason = is_blocked(command)
    if reason:
        print(f"secret-guard: blocked — {reason}. Use the value via env vars, never print it.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
