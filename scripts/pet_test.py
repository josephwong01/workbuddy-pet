"""
pet_test.py - 手动测试 WorkBuddy 桌面宠物（IP 熊）各状态。

原理：直接把状态推给本地 daemon（端口 19876），宠物（wb_pet.py）轮询 ~/.workbuddy/pet_state.json
后实时切换。等价于 WorkBuddy 钩子驱动，但不依赖真实对话。

用法（在 WorkBuddy-pet 目录，用 venv python 运行）：

  # 1) 循环播放全部 9 个精灵状态，每态停留 1.5 秒（最直观，推荐先跑这个）
  .venv/Scripts/python.exe scripts/pet_test.py cycle

  # 2) 循环播放真实 agent 钩子动作（thinking/running/waving/idle），验证映射
  .venv/Scripts/python.exe scripts/pet_test.py hooks

  # 3) 推送单个精灵状态（可带气泡消息）
  .venv/Scripts/python.exe scripts/pet_test.py waiting "正在思考..."
  .venv/Scripts/python.exe scripts/pet_test.py failed  "出错了！"
  .venv/Scripts/python.exe scripts/pet_test.py jumping
  .venv/Scripts/python.exe scripts/pet_test.py review  "检索中"

  # 4) 推送单个 agent 钩子动作（走 wb_pet 的 ALIASES 映射：
  #    thinking→waiting, running→running, waving→waving, idle→idle, agree→waiting）
  .venv/Scripts/python.exe scripts/pet_test.py --hook thinking
  .venv/Scripts/python.exe scripts/pet_test.py --hook running

  # 5) 列出所有可用状态名
  .venv/Scripts/python.exe scripts/pet_test.py --list

  # 6) 复位到 idle
  .venv/Scripts/python.exe scripts/pet_test.py idle

精灵层 9 状态：idle / running-right / running-left / waving / jumping /
              failed / waiting / running / review
"""
import sys
import time
import json
import urllib.request
import urllib.error

DAEMON_URL = "http://127.0.0.1:19876"

# 精灵层 9 状态（与 make_pet_from_static.py 的 STATE_ORDER 一致）
SPRITE_STATES = [
    "idle", "running-right", "running-left", "waving",
    "jumping", "failed", "waiting", "running", "review",
]

# agent 钩子动作（经 wb_pet ALIASES 映射后落到的精灵状态）
HOOK_ACTIONS = ["thinking", "running", "waving", "agree", "idle"]


def push(state, message="", timeout=2.0):
    """POST 一个状态到 daemon；返回 (ok, info)。"""
    payload = json.dumps({"state": state, "message": message}).encode("utf-8")
    req = urllib.request.Request(
        DAEMON_URL + "/set", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        return False, {"error": str(e)}
    except Exception as e:  # noqa
        return False, {"error": repr(e)}


def status():
    try:
        with urllib.request.urlopen(DAEMON_URL + "/status", timeout=2.0) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa
        return None


def cycle(names, dwell=1.5, label="状态"):
    print(f"[test] 循环播放 {label}（每态 {dwell}s），请勿关闭宠物窗口…\n")
    for i, name in enumerate(names, 1):
        ok, info = push(name, f"[{i}/{len(names)}] {name}")
        if not ok:
            print(f"  ✗ {name:<14} 推送失败: {info}")
            continue
        print(f"  {i:>2}/{len(names)}  {name:<14} 已应用")
        time.sleep(dwell)
    # 复位
    push("idle", "")
    print("\n[test] 已复位到 idle。")
    st = status()
    if st:
        print(f"[test] daemon 当前状态: {st.get('state')}")


def main():
    args = sys.argv[1:]

    if not args or args[0] in ("--list", "-l"):
        print("精灵层 9 状态：")
        for s in SPRITE_STATES:
            print("   ", s)
        print("\nagent 钩子动作（--hook 模式）：")
        for s in HOOK_ACTIONS:
            print("   ", s)
        return

    if args[0] == "cycle":
        duty = 1.5
        if len(args) > 1 and args[1].replace(".", "", 1).isdigit():
            duty = float(args[1])
        cycle(SPRITE_STATES, dwell=duty, label="精灵状态")
        return

    if args[0] == "hooks":
        duty = 1.5
        if len(args) > 1 and args[1].replace(".", "", 1).isdigit():
            duty = float(args[1])
        cycle(HOOK_ACTIONS, dwell=duty, label="agent 钩子动作")
        return

    # 单状态推送
    hook_mode = False
    if args[0] == "--hook":
        hook_mode = True
        target = args[1] if len(args) > 1 else "thinking"
        msg = args[2] if len(args) > 2 else ""
    else:
        target = args[0]
        msg = args[1] if len(args) > 1 else ""

    ok, info = push(target, msg)
    if not ok:
        print(f"[test] ✗ 推送失败：{info}")
        print("[test] 请确认宠物已启动（launch_wb_pet.py），daemon 默认 19876。")
        sys.exit(1)
    print(f"[test] 已推送 {('钩子动作' if hook_mode else '精灵状态')}: {target}"
          + (f"  气泡: {msg}" if msg else ""))
    st = status()
    if st:
        print(f"[test] daemon 当前状态: {st.get('state')}  "
              f"(宠物经 ALIASES 映射后显示: {_alias(st.get('state'))})")


def _alias(raw):
    # 复刻 wb_pet 的 ALIASES，便于在测试结果里提示最终精灵状态
    ALIASES = {
        "thinking": "waiting", "coding": "running", "debugging": "failed",
        "reading": "review", "writing": "running", "searching": "running-right",
        "agree": "waiting", "idle": "idle", "running": "running",
        "waving": "waving", "failed": "failed", "jumping": "jumping",
        "waiting": "waiting", "review": "review",
        "running-left": "running-left", "running-right": "running-right",
    }
    return ALIASES.get(raw, raw)


if __name__ == "__main__":
    main()
