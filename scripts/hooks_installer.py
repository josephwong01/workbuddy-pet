"""
hooks_installer.py - Wire WorkBuddy hooks to THIS executable.

When the user clicks "Connect my WorkBuddy" in the tray menu, we write a
SessionStart hook (to launch the pet) plus per-event hooks (to push agent
state) into ~/.workbuddy/settings.json.  All commands point at the running
executable (sys.executable) so the package is fully self-contained.

Idempotent: re-running only (re)adds our marked hooks, never duplicates.
"""
import os
import json
import sys

SETTINGS = os.path.join(os.path.expanduser("~"), ".workbuddy", "settings.json")
MARKER = "workbuddy-pet"

# 旧版接线（launch_wb_pet / petdex_bridge / desktop_pet / wb_pet.py）会在接入新版
# exe 时造成“双宠物”，安装时一并清除。
LEGACY_MARKERS = ("launch_wb_pet", "petdex_bridge", "desktop_pet", "wb_pet.py", "workbuddy_pet.py")

# (event, action-name, state, message)  action-name maps to the pet animation
HOOK_PLAN = [
    ("UserPromptSubmit", "thinking", "收到，思考中…"),
    ("PreToolUse", "thinking", "执行工具…"),
    ("PostToolUse", "running", "工作中…"),
    ("Stop", "waving", "完成 ✓"),
    ("SessionEnd", "idle", ""),
]


def _quote(p):
    return '"' + p.replace('"', '\\"') + '"'


def _state_cmd(exe, state, msg=""):
    if msg:
        return f"{_quote(exe)} --state {state} {_quote(msg)}"
    return f"{_quote(exe)} --state {state}"


def _is_ours(cmd):
    return MARKER in cmd


def _is_legacy(cmd):
    c = (cmd or "").lower()
    return any(m.lower() in c for m in LEGACY_MARKERS)


def install_hooks(exe_path=None):
    exe = exe_path or sys.executable
    settings = {}
    if os.path.exists(SETTINGS):
        try:
            with open(SETTINGS, "r", encoding="utf-8") as f:
                settings = json.load(f)
        except (OSError, json.JSONDecodeError):
            settings = {}
    hooks = settings.setdefault("hooks", {})

    # 清除旧版接线（launch_wb_pet / petdex_bridge 等），避免双宠物
    for event, entries in list(hooks.items()):
        for entry in entries:
            entry["hooks"] = [h for h in entry.get("hooks", [])
                              if not _is_legacy(h.get("command", ""))]
        hooks[event] = [e for e in entries if e.get("hooks")]

    # Sessions start -> launch the pet (no-op if already running)
    sess = hooks.setdefault("SessionStart", [])
    if not any(_is_ours(e.get("command", "")) for entry in sess for e in entry.get("hooks", [])):
        sess.append({"hooks": [{"type": "command", "command": _quote(exe), "timeout": 5}]})

    # Per-event state pushes
    for event, state, msg in HOOK_PLAN:
        entries = hooks.setdefault(event, [])
        # remove any previous ours for this event (so we can re-point if exe moved)
        for entry in entries:
            entry["hooks"] = [h for h in entry.get("hooks", []) if not _is_ours(h.get("command", ""))]
        entries.append({"hooks": [{"type": "command",
                                  "command": _state_cmd(exe, state, msg), "timeout": 5}]})

    os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
    with open(SETTINGS, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
    return True


def uninstall_hooks():
    if not os.path.exists(SETTINGS):
        return False
    try:
        with open(SETTINGS, "r", encoding="utf-8") as f:
            settings = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False
    hooks = settings.get("hooks", {})
    for event, entries in hooks.items():
        for entry in entries:
            entry["hooks"] = [h for h in entry.get("hooks", []) if not _is_ours(h.get("command", ""))]
        # drop empty entries
        hooks[event] = [e for e in entries if e.get("hooks")]
    settings["hooks"] = {k: v for k, v in hooks.items() if v}
    with open(SETTINGS, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)
    return True


def hooks_installed():
    if not os.path.exists(SETTINGS):
        return False
    try:
        with open(SETTINGS, "r", encoding="utf-8") as f:
            settings = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False
    for event, entries in settings.get("hooks", {}).items():
        for entry in entries:
            if any(_is_ours(h.get("command", "")) for h in entry.get("hooks", [])):
                return True
    return False


if __name__ == "__main__":
    install_hooks()
    print("hooks installed:", hooks_installed())
