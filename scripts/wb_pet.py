"""
wb_pet.py - WorkBuddy 内置桌面宠物（IP 熊，可拖拽，轻量）

设计目标（针对 PetDex Desktop 的三个痛点）：
  1) 不用任何外部重程序：纯 Tkinter，无 Electron，不卡。
  2) 可拖拽：无边框透明窗 + 鼠标手动拖拽（避开 Electron 透明窗命中测试坑）。
  3) 内置 WorkBuddy：轮询 ~/.workbuddy/pet_state.json（由 hooks→daemon 写入），
     并通过 SessionStart hook 随 WorkBuddy 会话自动唤起。

精灵图规范（与 make_pet_from_static.py 产出一致）：
  - 单张 PNG，8 列 × 9 行网格，每帧 192×208，整图 1536×1872。
  - 9 个状态按行 0..8：idle / running-right / running-left / waving /
    jumping / failed / waiting / running / review。
  - 配套 pet.json：{"states":[{"name","row","frames","durations"}...], "slug"}

用法：
  python wb_pet.py --atlas <ip-bear_atlas.png> --manifest <pet.json> [--scale 1.3]
  （atlas/manifest 均可省略，会自动定位项目内 output/ip-bear 或 assets/ip-bear）
"""
import os
import sys
import json
import time
import argparse
import threading
import tkinter as tk
from PIL import Image, ImageTk, ImageDraw

# ── 透明色键：窗口背景用此色，Tkinter 将其变透明 ──
TRANSPARENT_COLOR = "#F2F2F4"

# ── 精灵图尺寸 ──
FRAME_W = 192
FRAME_H = 208
COLS = 8
ROWS = 9

# ── 动画轮询/漫游参数 ──
STATE_POLL_MS = 150          # 状态文件轮询间隔
WANDER_INTERVAL = 6000       # 随机漫游间隔
WANDER_STEP = 60             # 每次漫游步长(px)
DEFAULT_FPS = 10

# 聊天状态 → 动画状态映射（petdex_bridge 写入的 state 原样即可，这里兜底）
ALIASES = {
    "thinking": "waiting",
    "coding": "running",
    "debugging": "failed",
    "reading": "review",
    "writing": "running",
    "searching": "running-right",
    "agree": "waiting",
    "idle": "idle",
    "running": "running",
    "waving": "waving",
    "failed": "failed",
    "jumping": "jumping",
    "waiting": "waiting",
    "review": "review",
    "running-left": "running-left",
    "running-right": "running-right",
}

ZORDER_TOPMOST = -1

STATE_FILE = os.path.join(os.path.expanduser("~"), ".workbuddy", "pet_state.json")
# 用户偏好（大小/位置/聊天感知）持久化，本机重启后保留
CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".workbuddy", "wb_pet_config.json")

# 缩放范围（智驾区间，避免过小看不见或过大挡屏）
SCALE_MIN = 0.5
SCALE_MAX = 3.0
SCALE_STEP = 1.15  # 滚轮/菜单每级缩放倍率


def load_config():
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def save_config(cfg):
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False)
    except OSError:
        pass


# ────────────────────────────────────────────────────────────
# 极简气泡（内联，避免外部依赖）
# ────────────────────────────────────────────────────────────
class MiniBubble:
    def __init__(self, root: tk.Tk):
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        try:
            self.win.wm_attributes("-transparentcolor", TRANSPARENT_COLOR)
        except Exception:
            pass
        self.canvas = tk.Canvas(self.win, bg=TRANSPARENT_COLOR, highlightthickness=0)
        self.canvas.pack()
        self.win.withdraw()
        self.visible = False
        self.w = 0
        self.h = 0

    def show(self, text: str, x: int, y: int):
        if not text or not text.strip():
            return
        self._draw(text)
        self.win.geometry(f"+{x}+{y}")
        self.win.deiconify()
        self.win.lift()
        self.visible = True

    def hide(self):
        if self.visible:
            self.win.withdraw()
            self.visible = False

    def move(self, x: int, y: int):
        if self.visible:
            self.win.geometry(f"+{x}+{y}")

    def destroy(self):
        try:
            self.win.destroy()
        except Exception:
            pass

    def _draw(self, text: str):
        self.canvas.delete("all")
        font = ("Microsoft YaHei", 10, "bold")
        lines = text.split("\n")
        maxw = 0
        for ln in lines:
            tid = self.canvas.create_text(0, 0, text=ln, font=font, anchor="nw")
            bbox = self.canvas.bbox(tid)
            self.canvas.delete(tid)
            if bbox:
                maxw = max(maxw, bbox[2] - bbox[0])
        pad = 8
        bw = max(maxw + pad * 2, 40)
        bh = len(lines) * 16 + pad * 2 + 6
        # 背景
        self.canvas.create_rectangle(0, 0, bw, bh - 6, fill="#f8f8f0", outline="")
        # 角上透明缺口（伪透明）
        n = 3
        for (nx, ny) in [(0, 0), (bw - n, 0), (0, bh - 6 - n), (bw - n, bh - 6 - n)]:
            self.canvas.create_rectangle(nx, ny, nx + n, ny + n, fill=TRANSPARENT_COLOR, outline="")
        # 边框
        self.canvas.create_rectangle(1, 1, bw - 1, bh - 7, outline="#3a3a3a", width=1)
        # 箭头
        ax = bw // 2
        self.canvas.create_polygon(ax - 5, bh - 6, ax + 5, bh - 6, ax, bh,
                                   fill="#f8f8f0", outline="#3a3a3a", width=1)
        for i, ln in enumerate(lines):
            self.canvas.create_text(bw // 2, pad + i * 16, text=ln, font=font,
                                   fill="#3a3a3a", anchor="n")
        self.w = bw
        self.h = bh
        self.canvas.config(width=bw, height=bh)


# ────────────────────────────────────────────────────────────
# 宠物主类
# ────────────────────────────────────────────────────────────
class WBPet:
    def __init__(self, atlas_path, manifest_path=None, scale=1.3,
                 state_file=STATE_FILE, chat_aware=True):
        self.scale = scale
        self.src_fw, self.src_fh = FRAME_W, FRAME_H  # 精灵图单帧尺寸（来自 manifest，可 !=192x208）
        self.fw = int(self.src_fw * scale)
        self.fh = int(self.src_fh * scale)
        self.current_state = "idle"
        self.current_frame = 0
        self.dragging = False
        self.drag_offset = (0, 0)
        self._drag_prev_x = 0
        self._pre_drag_state = "idle"
        self.wander_job = None
        self.chat_aware = chat_aware
        self.state_file = state_file
        self.last_mtime = 0
        self.last_chat_state = None

        # 加载精灵图
        if not os.path.exists(atlas_path):
            raise FileNotFoundError(f"精灵图不存在: {atlas_path}")
        self.atlas = Image.open(atlas_path).convert("RGBA")

        # 加载 manifest（决定状态行与帧数/时长）
        self.states = {}
        if manifest_path and os.path.exists(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    man = json.load(f)
                self.src_fw = man.get("frame_width", FRAME_W)
                self.src_fh = man.get("frame_height", FRAME_H)
                for s in man.get("states", []):
                    self.states[s["name"]] = {
                        "row": s.get("row", 0),
                        "frames": s.get("frames", COLS),
                        "durations": s.get("durations", []),
                    }
            except (OSError, json.JSONDecodeError):
                pass
        if not self.states:
            # 兜底：标准 9 状态
            names = ["idle", "running-right", "running-left", "waving",
                     "jumping", "failed", "waiting", "running", "review"]
            for i, nm in enumerate(names):
                self.states[nm] = {"row": i, "frames": COLS, "durations": []}

        # manifest 可能带来非 192x208 的帧尺寸，重算窗口尺寸
        self.fw = int(self.src_fw * scale)
        self.fh = int(self.src_fh * scale)

        # 窗口
        self.root = tk.Tk()
        self.root.title("WorkBuddy 宠物 · IP 熊")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        try:
            self.root.wm_attributes("-transparentcolor", TRANSPARENT_COLOR)
        except Exception:
            pass

        self.canvas = tk.Canvas(self.root, width=self.fw, height=self.fh,
                                bg=TRANSPARENT_COLOR, highlightthickness=0)
        self.canvas.pack()
        self.photo_item = self.canvas.create_image(0, 0, anchor="nw")

        self.bubble = MiniBubble(self.root)

        # 事件
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Double-Button-1>", self._on_double)
        self.canvas.bind("<ButtonPress-3>", self._show_menu)
        # 注意：滚轮缩放已移出宠物本体，仅保留在右键「设置」菜单中，
        # 避免与页面其它滚轮行为冲突。

        # 右键菜单：顶层只有「设置」下拉 + 「退出宠物」（模仿 PetDex 的窗口式设置）
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="退出宠物", command=self._quit)

        self.settings_menu = tk.Menu(self.menu, tearoff=0)
        self.chat_var = tk.BooleanVar(value=self.chat_aware)
        self.settings_menu.add_command(label="放大  ＋", command=lambda: self._rescale(self.scale * SCALE_STEP))
        self.settings_menu.add_command(label="缩小  －", command=lambda: self._rescale(self.scale / SCALE_STEP))
        self.settings_menu.add_separator()
        for lbl, sc in [("小 (0.8×)", 0.8), ("中 (1.3×)", 1.3), ("大 (1.8×)", 1.8), ("特大 (2.4×)", 2.4)]:
            self.settings_menu.add_command(label=lbl, command=lambda s=sc: self._rescale(s))
        self.settings_menu.add_separator()
        self.settings_menu.add_command(label="重置位置", command=self._reset_position)
        self.settings_menu.add_checkbutton(label="聊天感知", variable=self.chat_var,
                                           command=lambda: (setattr(self, "chat_aware", self.chat_var.get()), self._persist()))
        self.menu.add_cascade(label="设置 ▶", menu=self.settings_menu)

        # 初始位置：优先用上次的（记忆），否则右下角
        cfg = load_config()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        saved_x, saved_y = cfg.get("x"), cfg.get("y")
        if isinstance(saved_x, int) and isinstance(saved_y, int):
            x = max(0, min(saved_x, sw - self.fw))
            y = max(0, min(saved_y, sh - self.fh))
        else:
            x, y = sw - self.fw - 40, sh - self.fh - 40
        self.root.geometry(f"+{x}+{y}")
        # 记忆打开时的缩放/聊天感知偏好
        self.frames = {}
        if isinstance(cfg.get("scale"), (int, float)):
            self._rescale(cfg["scale"], silent=True)

        # 预缓存帧
        self.frames = {}
        self._precache()

        self._animate()
        if self.chat_aware:
            self._poll()

    # ── 帧加载 ──
    def _precache(self):
        for name, info in self.states.items():
            row = info["row"]
            self.frames[name] = []
            for col in range(info["frames"]):
                x1, y1 = col * self.src_fw, row * self.src_fh
                fr = self.atlas.crop((x1, y1, x1 + self.src_fw, y1 + self.src_fh))
                fr = fr.resize((self.fw, self.fh), Image.LANCZOS)
                self.frames[name].append(ImageTk.PhotoImage(fr))

    # ── 动画循环 ──
    def _animate(self):
        info = self.states.get(self.current_state)
        if not info:
            return
        seq = self.frames.get(self.current_state, [])
        if not seq:
            return
        self.current_frame %= len(seq)
        self.canvas.itemconfig(self.photo_item, image=seq[self.current_frame])
        durs = info.get("durations", [])
        if durs and self.current_frame < len(durs):
            delay = durs[self.current_frame]
        else:
            delay = int(1000 / DEFAULT_FPS)
        self.current_frame += 1
        self.root.after(delay, self._animate)

    def set_state(self, name):
        if name in self.states:
            self.current_state = name
            self.current_frame = 0

    # ── 状态轮询 ──
    def _poll(self):
        try:
            if os.path.exists(self.state_file):
                mtime = os.path.getmtime(self.state_file)
                if mtime > self.last_mtime:
                    self.last_mtime = mtime
                    with open(self.state_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    raw = data.get("state", "idle")
                    msg = data.get("message", "")
                    anim = ALIASES.get(raw, raw)
                    if anim not in self.states:
                        anim = "idle"
                    if raw != self.last_chat_state:
                        self.last_chat_state = raw
                        self.set_state(anim)
                        if msg:
                            self._show_bubble(msg)
                        else:
                            self.bubble.hide()
        except (OSError, json.JSONDecodeError):
            pass
        self.root.after(STATE_POLL_MS, self._poll)

    # ── 气泡定位 ──
    def _content_top(self):
        info = self.states.get(self.current_state)
        if not info:
            return 0
        row = info["row"]
        for py in range(self.src_fh):
            for px in range(0, self.src_fw, 4):
                p = self.atlas.getpixel((px, row * self.src_fh + py))
                if len(p) == 4 and p[3] > 0 and not (p[0] > 240 and p[1] > 240 and p[2] > 240):
                    return int(py * self.scale)
        return 0

    def _show_bubble(self, text):
        if not text or not text.strip():
            return
        self.bubble._draw(text)
        px = self.root.winfo_x()
        py = self.root.winfo_y()
        off = (self.fw - self.bubble.w) // 2 if self.bubble.w < self.fw else -20
        self.bubble.show(text, px + off, py + self._content_top() - self.bubble.h + 2)

    # ── 拖拽 ──
    def _on_press(self, e):
        self.dragging = True
        xr = e.widget.winfo_rootx() + e.x
        yr = e.widget.winfo_rooty() + e.y
        self.drag_offset = (xr - self.root.winfo_x(), yr - self.root.winfo_y())
        self._drag_prev_x = xr
        self._pre_drag_state = self.current_state
        # 抓取指针：拖动中即使划过透明边也不丢事件（修复"只有头部抓得住"）
        try:
            self.canvas.grab_set()
        except Exception:
            pass

    def _on_drag(self, e):
        if not self.dragging:
            return
        xr = e.widget.winfo_rootx() + e.x
        yr = e.widget.winfo_rooty() + e.y
        dx = xr - self._drag_prev_x
        if dx > 3:
            self.set_state("running-right")
        elif dx < -3:
            self.set_state("running-left")
        self._drag_prev_x = xr
        x = xr - self.drag_offset[0]
        y = yr - self.drag_offset[1]
        self.root.geometry(f"+{x}+{y}")
        if self.bubble.visible:
            off = (self.fw - self.bubble.w) // 2 if self.bubble.w < self.fw else -20
            self.bubble.move(x + off, y + self._content_top() - self.bubble.h + 2)

    def _on_release(self, e):
        self.dragging = False
        try:
            self.canvas.grab_release()
        except Exception:
            pass
        self.set_state(self._pre_drag_state)
        self._persist()  # 记住位置

    def _on_double(self, e):
        names = list(self.states.keys())
        if self.current_state in names:
            i = names.index(self.current_state)
            self.set_state(names[(i + 1) % len(names)])

    # ── 缩放（仅右键「设置」菜单，不在宠物本体绑定滚轮）──
    def _rescale(self, new_scale, silent=False):
        new_scale = max(SCALE_MIN, min(SCALE_MAX, new_scale))
        if abs(new_scale - self.scale) < 0.01:
            return
        self.scale = new_scale
        self.fw = int(self.src_fw * self.scale)
        self.fh = int(self.src_fh * self.scale)
        self.canvas.config(width=self.fw, height=self.fh)
        # 重新预缓存所有状态帧
        self.frames = {}
        self._precache()
        if not silent:
            self._persist()
            # 缩放后若气泡可见则重定位
            if self.bubble.visible:
                px, py = self.root.winfo_x(), self.root.winfo_y()
                off = (self.fw - self.bubble.w) // 2 if self.bubble.w < self.fw else -20
                self.bubble.move(px + off, py + self._content_top() - self.bubble.h + 2)

    def _reset_position(self):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"+{sw - self.fw - 40}+{sh - self.fh - 40}")
        self._persist()

    # ── 偏好持久化 ──
    def _persist(self):
        save_config({
            "scale": round(self.scale, 3),
            "x": self.root.winfo_x(),
            "y": self.root.winfo_y(),
            "chat_aware": self.chat_aware,
        })

    def _show_menu(self, e):
        self.menu.tk_popup(e.x_root, e.y_root)

    # ── 生命周期 ──
    def _quit(self):
        self.bubble.destroy()
        try:
            self.root.destroy()
        except Exception:
            pass

    def reload(self, atlas_path, manifest_path=None, scale=None):
        """Hot-swap the sprite atlas at runtime (used by the pet selector)."""
        if not os.path.exists(atlas_path):
            return False
        self.atlas = Image.open(atlas_path).convert("RGBA")
        self.states = {}
        if manifest_path and os.path.exists(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    man = json.load(f)
                self.src_fw = man.get("frame_width", FRAME_W)
                self.src_fh = man.get("frame_height", FRAME_H)
                for s in man.get("states", []):
                    self.states[s["name"]] = {
                        "row": s.get("row", 0),
                        "frames": s.get("frames", COLS),
                        "durations": s.get("durations", []),
                    }
            except (OSError, json.JSONDecodeError):
                pass
        if not self.states:
            names = ["idle", "running-right", "running-left", "waving",
                     "jumping", "failed", "waiting", "running", "review"]
            for i, nm in enumerate(names):
                self.states[nm] = {"row": i, "frames": COLS, "durations": []}
        if scale is not None:
            self.scale = max(SCALE_MIN, min(SCALE_MAX, scale))
        self.fw = int(self.src_fw * self.scale)
        self.fh = int(self.src_fh * self.scale)
        self.canvas.config(width=self.fw, height=self.fh)
        self.frames = {}
        self._precache()
        self.set_state("idle")
        self._persist()
        return True

    def run(self):
        self.root.mainloop()


# ────────────────────────────────────────────────────────────
# 自动定位精灵图
# ────────────────────────────────────────────────────────────
def _find_default_assets():
    """返回 (atlas, manifest) 或 (None, None)。"""
    here = os.path.dirname(os.path.abspath(__file__))
    project = os.path.dirname(here)
    candidates = [
        os.path.join(project, "output", "ip-bear"),
        os.path.join(project, "assets", "ip-bear"),
        os.path.join(project, "output"),
    ]
    for d in candidates:
        atlas = os.path.join(d, "ip-bear_atlas.png")
        manifest = os.path.join(d, "pet.json")
        if os.path.exists(atlas):
            return atlas, manifest if os.path.exists(manifest) else None
    return None, None


def main():
    ap = argparse.ArgumentParser(description="WorkBuddy 桌面宠物 (IP 熊)")
    ap.add_argument("--atlas", default=None)
    ap.add_argument("--manifest", default=None)
    ap.add_argument("--scale", type=float, default=None,
                    help="缩放倍率；省略则使用上次保存的偏好（默认 1.3）")
    ap.add_argument("--state-file", default=STATE_FILE)
    ap.add_argument("--no-chat-aware", action="store_true")
    args = ap.parse_args()

    atlas, manifest = args.atlas, args.manifest
    if not atlas:
        atlas, manifest = _find_default_assets()

    if not atlas:
        print("ERROR: 找不到 IP 熊精灵图。请先运行 make_pet_from_static.py 生成。", file=sys.stderr)
        sys.exit(1)

    # 缩放优先级：命令行 --scale > 已保存偏好 > 默认 1.3
    effective_scale = args.scale if args.scale else load_config().get("scale", 1.3)

    pet = WBPet(atlas, manifest, effective_scale, args.state_file,
                chat_aware=not args.no_chat_aware)
    pet.run()


if __name__ == "__main__":
    main()
