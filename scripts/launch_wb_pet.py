"""
launch_wb_pet.py - WorkBuddy 内置桌面宠物入口

职责：
  1) 自动定位 IP 熊精灵图（output/ip-bear 优先，回退 assets/ip-bear）。
  2) 确保状态 daemon(端口 19876) 在运行；未运行则拉起 pet_daemon.py。
  3) 以无窗口方式拉起 wb_pet.py（可拖拽 Tkinter 宠物）。

运行期控制：
  python launch_wb_pet.py            # 打开（已开则跳过，单实例）
  python launch_wb_pet.py --stop     # 关闭当前宠物
  python launch_wb_pet.py --scale 1.8  # 以指定大小打开（覆盖记忆偏好）

设计：全程用 subprocess.Popen（非阻塞），可被 WorkBuddy 的 SessionStart hook 调用，
不会卡住 WorkBuddy 自身。单实例由 PID 文件 ~/.workbuddy/wb_pet.pid 保证。
"""
import os
import sys
import time
import socket
import subprocess

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPTS_DIR)
DAEMON_PORT = 19876
PID_FILE = os.path.join(os.path.expanduser("~"), ".workbuddy", "wb_pet.pid")


def _popen_kwargs():
    kw = {}
    if sys.platform == "win32":
        try:
            kw["creationflags"] = subprocess.CREATE_NO_WINDOW
        except AttributeError:
            pass
    return kw


def find_ip_bear_assets():
    candidates = [
        os.path.join(PROJECT_DIR, "output", "ip-bear"),
        os.path.join(PROJECT_DIR, "assets", "ip-bear"),
    ]
    for d in candidates:
        atlas = os.path.join(d, "ip-bear_atlas.png")
        manifest = os.path.join(d, "pet.json")
        if os.path.exists(atlas):
            return atlas, manifest if os.path.exists(manifest) else None
    return None, None


def daemon_alive():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        s.connect(("127.0.0.1", DAEMON_PORT))
        s.close()
        return True
    except OSError:
        return False


def _read_pid():
    try:
        if os.path.exists(PID_FILE):
            with open(PID_FILE, "r", encoding="utf-8") as f:
                return int(f.read().strip())
    except (OSError, ValueError):
        pass
    return None


def _pid_alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # 进程存在但无权限发信号 → 仍视为存活
        return True
    except OSError:
        return False


def stop_pet():
    pid = _read_pid()
    if pid and _pid_alive(pid):
        try:
            # Windows 下用 taskkill 干净结束（含子进程）
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            print(f"[wb_pet] 已关闭宠物 (pid={pid})")
        except Exception as e:
            print(f"[wb_pet] 关闭失败: {e}", file=sys.stderr)
    else:
        print("[wb_pet] 没有运行中的宠物")
    try:
        os.remove(PID_FILE)
    except OSError:
        pass


def launch(scale=None):
    # 单实例：已运行则跳过
    if _pid_alive(_read_pid()):
        print("[wb_pet] 宠物已在运行，跳过。")
        return

    python = sys.executable
    kw = _popen_kwargs()

    # 1) 定位精灵图
    atlas, manifest = find_ip_bear_assets()
    if not atlas:
        print("[wb_pet] 未找到 IP 熊精灵图，请先运行 make_pet_from_static.py。", file=sys.stderr)
        sys.exit(1)
    print(f"[wb_pet] 精灵图: {atlas}")

    # 2) 确保 daemon
    if daemon_alive():
        print("[wb_pet] daemon 已在运行")
    else:
        print("[wb_pet] 启动 daemon ...")
        subprocess.Popen([python, os.path.join(SCRIPTS_DIR, "pet_daemon.py")], **kw)
        time.sleep(1)

    # 3) 拉起宠物
    cmd = [python, os.path.join(SCRIPTS_DIR, "wb_pet.py"), "--atlas", atlas]
    if manifest:
        cmd += ["--manifest", manifest]
    if scale:
        cmd += ["--scale", str(scale)]
    proc = subprocess.Popen(cmd, **kw)
    try:
        with open(PID_FILE, "w", encoding="utf-8") as f:
            f.write(str(proc.pid))
    except OSError:
        pass
    print(f"[wb_pet] 宠物已启动（pid={proc.pid}，可拖拽）。")


if __name__ == "__main__":
    stop = "--stop" in sys.argv
    scale_arg = None
    if "--scale" in sys.argv:
        i = sys.argv.index("--scale")
        if i + 1 < len(sys.argv):
            try:
                scale_arg = float(sys.argv[i + 1])
            except ValueError:
                pass
    if stop:
        stop_pet()
    else:
        launch(scale=scale_arg)
