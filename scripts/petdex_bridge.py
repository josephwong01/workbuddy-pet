"""
petdex_bridge.py - Forward WorkBuddy agent state to PetDex Desktop.

Usage (same interface as pet_bridge.py):
    python petdex_bridge.py thinking "正在思考..."
    python petdex_bridge.py running  "工作中..."
    python petdex_bridge.py waving   "完成！"
    python petdex_bridge.py idle
    python petdex_bridge.py failed
    python petdex_bridge.py agree

It POSTs the mapped state to PetDex Desktop's local HTTP hook server
(http://127.0.0.1:7777/state) using the per-session token at
~/.petdex/runtime/update-token. Best-effort: if PetDex isn't running
or the token file is missing, it silently no-ops so WorkBuddy hooks
never fail.

It also forwards to the local pet_daemon (port 19876) so the Tkinter
pet from step (1) keeps working alongside PetDex.
"""
import os
import sys
import json
import urllib.request

PETDEX_PORT = 7777
PETDEX_STATE_URL = "http://127.0.0.1:{0}/state".format(PETDEX_PORT)
PETDEX_TOKEN_PATH = os.path.join(
    os.path.expanduser("~"), ".petdex", "runtime", "update-token"
)

DAEMON_URL = "http://127.0.0.1:19876"

# WorkBuddy-pet states -> PetDex renderer states
# (PetDex supports: idle, running, running-right, running-left,
#  waving, jumping, failed, waiting, review)
STATE_MAP = {
    "thinking": "running",
    "running": "running",
    "waving": "waving",
    "idle": "idle",
    "failed": "failed",
    "agree": "waiting",
}


def _post(url, payload, headers, timeout=1.0):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers=headers, method="POST"
    )
    urllib.request.urlopen(req, timeout=timeout)


def forward_petdex(state, message=""):
    try:
        with open(PETDEX_TOKEN_PATH, "r", encoding="utf-8") as f:
            token = f.read().strip()
    except OSError:
        return  # PetDex not running / not installed -> no-op
    if not token:
        return
    petdex_state = STATE_MAP.get(state, state)
    headers = {
        "Content-Type": "application/json",
        "X-Petdex-Update-Token": token,
    }
    try:
        _post(PETDEX_STATE_URL, {"state": petdex_state}, headers)
    except Exception:
        pass  # best-effort; never break the WorkBuddy hook


def forward_daemon(state, message=""):
    headers = {"Content-Type": "application/json"}
    try:
        _post(
            "{0}/set".format(DAEMON_URL),
            {"state": state, "message": message},
            headers,
        )
    except Exception:
        pass  # best-effort


def main():
    if len(sys.argv) < 2:
        sys.exit(0)
    action = sys.argv[1]
    msg = sys.argv[2] if len(sys.argv) > 2 else ""
    forward_petdex(action, msg)
    forward_daemon(action, msg)
    sys.exit(0)


if __name__ == "__main__":
    main()
