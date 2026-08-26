"""
app.py - WorkBuddy 桌面宠物 · 单一可执行入口（打包为 workbuddy-pet.exe）

运行模式（双击 exe / 无参数）：
  - 启动状态 daemon 线程（端口 19876，写入 ~/.workbuddy/pet_state.json）
  - 启动 Tkinter 宠物窗口（可拖拽、聊天感知）
  - 启动系统托盘图标（右键菜单：切换宠物 / DIY / 接入 WorkBuddy / 退出）

子命令（供 WorkBuddy hooks 调用）：
  --state <name> [msg]   推送一个状态（连接 daemon；若宠物未运行则先拉起）
  --install-hooks        把 hooks 写入 ~/.workbuddy/settings.json，指向本 exe
  --uninstall-hooks      移除上述 hooks
  --stop                 关闭运行中的宠物
  --diy                  打开“DIY 我的宠物”窗口
  --select               打开“选择宠物”窗口

打包：见 build.py（PyInstaller，单文件、隐藏控制台、捆绑内置宠物资源）。
"""
import os
import sys
import json
import time
import socket
import threading
import subprocess

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPTS_DIR)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import pet_constants as C          # noqa: E402
from wb_pet import WBPet, _find_default_assets, load_config  # noqa: E402
from pet_daemon import PetDaemon, PetHandler  # noqa: E402
import hooks_installer  # noqa: E402
import diy_gui  # noqa: E402

PID_FILE = os.path.join(os.path.expanduser("~"), ".workbuddy", "wb_pet.pid")
DAEMON_PORT = C.DAEMON_PORT
LOCK_PORT = 19877  # 单实例锁：run_mode 占用此端口，确保同一时刻只有一个宠物实例

_lock_socket = None  # 保持引用，使锁端口在进程存活期间一直占用


def acquire_lock():
    """占用 LOCK_PORT 作为单实例锁；已被占用返回 None。"""
    global _lock_socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", LOCK_PORT))
        s.listen(1)
        _lock_socket = s
        return s
    except OSError:
        return None


def lock_held():
    """是否有实例已占用锁端口（即已有宠物在运行/启动中）。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.3)
        s.connect(("127.0.0.1", LOCK_PORT))
        s.close()
        return True
    except OSError:
        return False

# 全局引用（宠物实例 + 其 Tk root），供托盘跨线程调度
PET = None
PET_ROOT = None
TRAY_ICON = None
DAEMON = None


# --------------------------------------------------------------------------
# 资源定位（打包后走 _MEIPASS，源码走项目目录）
# --------------------------------------------------------------------------
def asset_path(rel):
    if getattr(sys, "_MEIPASS", None):
        return os.path.join(sys._MEIPASS, rel)
    return os.path.join(PROJECT_DIR, rel)


def find_builtin_pets():
    """返回 [(name, atlas, manifest), ...] 内置宠物（打包资源 + output 兜底）。"""
    pets = []
    candidates = [
        asset_path(os.path.join("assets", "ip-bear")),
        os.path.join(PROJECT_DIR, "output", "ip-bear"),
    ]
    for d in candidates:
        atlas = os.path.join(d, "ip-bear_atlas.png")
        manifest = os.path.join(d, "pet.json")
        if os.path.exists(atlas):
            pets.append(("ip-bear (内置)", atlas, manifest if os.path.exists(manifest) else None))
            break
    return pets


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except Exception:
        return True


def _read_pid():
    try:
        with open(PID_FILE, "r", encoding="utf-8") as f:
            return int(f.read().strip())
    except Exception:
        return None


# --------------------------------------------------------------------------
# 托盘图标
# --------------------------------------------------------------------------
def make_tray_icon():
    """优先加载打包进 exe 的 logo 图标；找不到则回退到程序绘制的绿色小熊。"""
    from PIL import Image
    # 尝试加载内置图标（PyInstaller 打包后位于 _MEIPASS/assets/icon/）
    icon_candidates = [
        asset_path(os.path.join("assets", "icon", "app_icon.ico")),
        asset_path(os.path.join("assets", "icon", "logo_clean.png")),
        os.path.join(PROJECT_DIR, "assets", "icon", "app_icon.ico"),
        os.path.join(PROJECT_DIR, "assets", "icon", "logo_clean.png"),
    ]
    for path in icon_candidates:
        if os.path.isfile(path):
            try:
                img = Image.open(path).convert("RGBA")
                img.thumbnail((64, 64), Image.Resampling.LANCZOS)
                if img.size != (64, 64):
                    canvas = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
                    offset = ((64 - img.size[0]) // 2, (64 - img.size[1]) // 2)
                    canvas.paste(img, offset)
                    img = canvas
                print(f"[tray] Loaded icon: {path} -> {img.size}")
                return img
            except Exception as e:
                print(f"[tray] Failed to load {path}: {e}")
                continue

    # 回退：程序绘制绿色小熊
    from PIL import ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([8, 16, 56, 60], radius=14, fill=(34, 139, 34, 255),
                        outline=(20, 90, 20, 255), width=3)
    for cx in (26, 40):
        d.ellipse([cx - 7, 24, cx + 7, 38], fill=(255, 255, 255, 255))
        d.ellipse([cx - 3, 27, cx + 3, 33], fill=(15, 15, 15, 255))
    d.rounded_rectangle([28, 40, 36, 50], radius=3, fill=(212, 175, 55, 255))
    print("[tray] Using fallback drawn bear icon")
    return img


def _switch_pet(atlas, manifest):
    if PET and PET_ROOT:
        PET_ROOT.after(0, lambda: PET.reload(atlas, manifest))


def build_tray_menu():
    import pystray
    wb_on = hooks_installer.hooks_installed()

    def toggle_wb(icon, item):
        if hooks_installer.hooks_installed():
            hooks_installer.uninstall_hooks()
        else:
            hooks_installer.install_hooks()
        icon.update_menu()

    def diy(icon, item):
        if PET_ROOT:
            PET_ROOT.after(0, lambda: diy_gui.open_diy(PET_ROOT, refresh_tray_menu))

    def select(icon, item):
        if PET_ROOT:
            PET_ROOT.after(0, lambda: diy_gui.open_selector(
                PET_ROOT, find_builtin_pets(), _switch_pet))

    def quit_app(icon, item):
        stop_all()

    return pystray.Menu(
        pystray.MenuItem("切换宠物…", select),
        pystray.MenuItem("DIY 我的宠物…", diy),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("接入我的 WorkBuddy", toggle_wb, checked=lambda i: hooks_installer.hooks_installed()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出宠物", quit_app),
    )


def refresh_tray_menu():
    if TRAY_ICON:
        TRAY_ICON.update_menu()


# --------------------------------------------------------------------------
# 生命周期
# --------------------------------------------------------------------------
def start_daemon():
    global DAEMON
    DAEMON = PetDaemon()
    PetHandler.daemon = DAEMON
    server = socket_server(DAEMON)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


def socket_server(daemon):
    from http.server import HTTPServer
    srv = HTTPServer(("127.0.0.1", DAEMON_PORT), PetHandler)
    return srv


def start_pet():
    global PET, PET_ROOT
    atlas, manifest = _find_default_assets()
    if not atlas:
        builtin = find_builtin_pets()
        if builtin:
            _, atlas, manifest = builtin[0]
    if not atlas:
        print("ERROR: 找不到内置宠物资源。", file=sys.stderr)
        return False
    cfg = load_config()
    scale = cfg.get("scale", 1.3)
    PET = WBPet(atlas, manifest, scale, C.STATE_FILE, chat_aware=cfg.get("chat_aware", True))
    PET_ROOT = PET.root
    threading.Thread(target=PET.run, daemon=True).start()
    return True


def stop_all():
    try:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
    except OSError:
        pass
    try:
        if PET and PET_ROOT:
            PET_ROOT.after(0, PET._quit)
    except Exception:
        pass
    if DAEMON:
        try:
            DAEMON.shutdown()
        except Exception:
            pass
    if TRAY_ICON:
        TRAY_ICON.stop()
    time.sleep(0.3)
    sys.exit(0)


def run_mode():
    # 单实例：占用锁端口，已被占用则直接退出
    if acquire_lock() is None:
        print("[workbuddy-pet] 已在运行，本次跳过。")
        return

    start_daemon()
    if not start_pet():
        sys.exit(1)

    # 写 PID（用于 --stop / 单实例）
    try:
        with open(PID_FILE, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except OSError:
        pass

    import pystray
    global TRAY_ICON
    TRAY_ICON = pystray.Icon("workbuddy-pet", make_tray_icon(), "WorkBuddy 宠物")
    TRAY_ICON.menu = build_tray_menu()
    # 托盘在主线程运行；宠物 Tk 在子线程
    TRAY_ICON.run()


def daemon_reachable():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        s.connect(("127.0.0.1", DAEMON_PORT))
        s.close()
        return True
    except OSError:
        return False


def push_state(state, msg=""):
    # 已有实例在运行/启动中（锁端口被占用）：等待 daemon 起来后推送
    if not daemon_reachable():
        if lock_held():
            for _ in range(40):
                if daemon_reachable():
                    break
                time.sleep(0.15)
        else:
            # 完全没实例：拉起完整 app（宠物会出现），再等待推送
            try:
                subprocess.Popen([sys.executable],
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except Exception:
                pass
            for _ in range(40):
                if daemon_reachable():
                    break
                time.sleep(0.15)
    try:
        import urllib.request
        data = json.dumps({"state": state, "message": msg}).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{DAEMON_PORT}/set", data=data,
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=3)
        print(f"[workbuddy-pet] state -> {state}")
        return True
    except Exception as e:
        print(f"[workbuddy-pet] push failed: {e}", file=sys.stderr)
        return False


def stop_pet():
    pid = _read_pid()
    if pid and _pid_alive(pid):
        try:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception:
            pass
    try:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
    except OSError:
        pass
    print("[workbuddy-pet] 已关闭宠物")


def diy_standalone():
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    diy_gui.open_diy(root, refresh_tray_menu)
    root.mainloop()


def select_standalone():
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    diy_gui.open_selector(root, find_builtin_pets(), _switch_pet)
    root.mainloop()


# --------------------------------------------------------------------------
# 入口分发
# --------------------------------------------------------------------------
def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("run", "gui"):
        run_mode()
        return

    cmd = argv[0]
    if cmd == "--state":
        state = argv[1] if len(argv) > 1 else "idle"
        msg = argv[2] if len(argv) > 2 else ""
        push_state(state, msg)
    elif cmd == "--install-hooks":
        hooks_installer.install_hooks()
        print("hooks installed:", hooks_installer.hooks_installed())
    elif cmd == "--uninstall-hooks":
        hooks_installer.uninstall_hooks()
        print("hooks removed")
    elif cmd == "--stop":
        stop_pet()
    elif cmd == "--diy":
        diy_standalone()
    elif cmd == "--select":
        select_standalone()
    else:
        print("未知参数:", cmd)
        print("用法: workbuddy-pet.exe [--state <name> [msg] | --install-hooks | "
              "--uninstall-hooks | --stop | --diy | --select]")


if __name__ == "__main__":
    main()
