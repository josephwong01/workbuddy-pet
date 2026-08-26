"""
diy_gui.py - In-app "DIY your own pet" + pet selector (Tkinter).

Opened from the system-tray menu of the bundled executable.  Turns a single
static character image into a full 9-state sprite package using the same
offline pipeline as make_pet_from_static.py, and saves it under the user's
pets directory so it persists across runs.
"""
import os
import sys
import json
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

# make sibling scripts importable when frozen
SCRIPTS = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from make_pet_from_static import (  # noqa: E402
    fit_char, build_states, tighten, compose_atlas,
)


def user_pets_dir():
    d = os.path.join(os.path.expanduser("~"), ".workbuddy-pet", "pets")
    os.makedirs(d, exist_ok=True)
    return d


def list_user_pets():
    """Return [(name, atlas, manifest), ...] from the user pets directory."""
    out = []
    base = user_pets_dir()
    for slug in sorted(os.listdir(base)):
        d = os.path.join(base, slug)
        atlas = os.path.join(d, "atlas.png")
        manifest = os.path.join(d, "pet.json")
        if os.path.isdir(d) and os.path.exists(atlas):
            out.append((slug, atlas, manifest if os.path.exists(manifest) else None))
    return out


def open_diy(parent_root, refresh_cb=None):
    win = tk.Toplevel(parent_root)
    win.title("DIY 我的宠物")
    win.attributes("-topmost", True)
    win.resizable(False, False)

    tk.Label(win, text="用一张静态图生成你的桌面宠物", font=("Microsoft YaHei", 11, "bold")).grid(
        row=0, column=0, columnspan=3, pady=(10, 6), padx=12)

    tk.Label(win, text="图片：").grid(row=1, column=0, sticky="e", padx=6, pady=4)
    img_var = tk.StringVar()
    tk.Entry(win, textvariable=img_var, width=34).grid(row=1, column=1, padx=4, pady=4)
    tk.Button(win, text="浏览…", command=lambda: img_var.set(
        filedialog.askopenfilename(
            title="选择角色图片",
            filetypes=[("图片", "*.png;*.jpg;*.jpeg;*.webp;*.bmp")]))).grid(row=1, column=2, padx=6, pady=4)

    tk.Label(win, text="宠物ID：").grid(row=2, column=0, sticky="e", padx=6, pady=4)
    slug_var = tk.StringVar()
    tk.Entry(win, textvariable=slug_var, width=34).grid(row=2, column=1, columnspan=2, padx=4, pady=4, sticky="w")

    tk.Label(win, text="显示名：").grid(row=3, column=0, sticky="e", padx=6, pady=4)
    name_var = tk.StringVar()
    tk.Entry(win, textvariable=name_var, width=34).grid(row=3, column=1, columnspan=2, padx=4, pady=4, sticky="w")

    status = tk.Label(win, text="提示：透明背景 PNG 最佳；JPG 白底会自动抠除。", fg="#666", wraplength=360, justify="left")
    status.grid(row=4, column=0, columnspan=3, padx=10, pady=(4, 2))

    def do_generate():
        img = img_var.get().strip()
        slug = slug_var.get().strip()
        if not img or not os.path.exists(img):
            status.config(text="⚠ 请先选择一张存在的图片。", fg="#c00")
            return
        if not slug:
            status.config(text="⚠ 请填写宠物ID（英文/数字，如 my-bear）。", fg="#c00")
            return
        if not all(c.isalnum() or c in "-_" for c in slug):
            status.config(text="⚠ 宠物ID只能含字母/数字/连字符。", fg="#c00")
            return
        status.config(text="生成中…（抠背景 + 合成 9 状态精灵图）", fg="#06c")
        btn.config(state="disabled")

        def work():
            try:
                from PIL import Image
                base = fit_char(Image.open(img))
                states = build_states(base)
                states, fw, fh = tighten(states)
                out_dir = os.path.join(user_pets_dir(), slug)
                atlas_path, manifest_path = compose_atlas(
                    states, slug, name_var.get().strip() or slug, out_dir, fw=fw, fh=fh)
                parent_root.after(0, lambda: (
                    status.config(text=f"✓ 已生成 {slug}（{fw}x{fh}/帧，9 状态）", fg="#090"),
                    btn.config(state="normal"),
                    refresh_cb() if refresh_cb else None,
                    messagebox.showinfo("完成", f"宠物「{slug}」已生成！\n可在「选择宠物」里切换。"),
                ))
            except Exception as e:  # noqa
                parent_root.after(0, lambda: (
                    status.config(text=f"✗ 生成失败：{e}", fg="#c00"),
                    btn.config(state="normal")))

        threading.Thread(target=work, daemon=True).start()

    btn = tk.Button(win, text="生成宠物", command=do_generate, bg="#2a7", fg="white", width=14)
    btn.grid(row=5, column=0, columnspan=3, pady=(6, 12))


def open_selector(parent_root, builtin_pets, reload_cb):
    win = tk.Toplevel(parent_root)
    win.title("选择宠物")
    win.attributes("-topmost", True)
    win.resizable(False, False)

    tk.Label(win, text="点击切换当前宠物", font=("Microsoft YaHei", 11, "bold")).pack(pady=(10, 6))

    pets = list(builtin_pets) + list_user_pets()

    def pick(atlas, manifest):
        try:
            reload_cb(atlas, manifest)
            win.destroy()
        except Exception as e:  # noqa
            messagebox.showerror("切换失败", str(e))

    if not pets:
        tk.Label(win, text="（暂无宠物，去 DIY 一个吧）").pack(padx=20, pady=10)
    for name, atlas, manifest in pets:
        tk.Button(win, text=name, width=24, command=lambda a=atlas, m=manifest: pick(a, m)).pack(pady=2)

    tk.Button(win, text="＋ 新建 / DIY 宠物", width=24,
              command=lambda: (win.destroy(), open_diy(parent_root))).pack(pady=(6, 10))
