"""
build.py - 用 PyInstaller 把 app.py 打包成单文件 exe（workbuddy-pet.exe）。

用法：
  python build.py            # 产出 dist/workbuddy-pet.exe
"""
import os
import PyInstaller.__main__

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "scripts")
ASSETS = os.path.join(HERE, "assets")

PyInstaller.__main__.run([
    os.path.join(SCRIPTS, "app.py"),
    "--name", "workbuddy-pet",
    "--onefile",
    "--windowed",               # 无控制台窗口（宠物是 GUI）
    "--noconfirm",
    f"--paths={SCRIPTS}",
    # 内置宠物资源（ip-bear 精灵图 + pet.json）打进 exe
    f"--add-data={ASSETS}{os.pathsep}assets",
    "--hidden-import=pystray",
    "--hidden-import=PIL",
    "--hidden-import=PIL.Image",
    "--hidden-import=PIL.ImageTk",
    "--hidden-import=PIL.ImageDraw",
    "--hidden-import=tkinter",
    "--hidden-import=tkinter.ttk",
    "--hidden-import=http.server",
    "--hidden-import=urllib.request",
    "--collect-submodules=pystray",
    "--collect-submodules=PIL",
    "--log-level", "WARN",
])
