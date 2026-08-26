# WorkBuddy Pet · 桌面宠物

把 Codex / Claude Code 同款的「动画桌面宠物」搬进 WorkBuddy。宠物常驻桌面、可拖拽、随 AI 工作状态实时切换动画，并支持**用一张静态图 DIY 自己的宠物**，打包成单文件 EXE 分享给任何人。

> 内置示例宠物：**IP 熊**（科技感 PCB 吉祥物），已随 EXE 打包。

## 功能特性

- 透明可拖拽：无边框透明窗，整只宠物可拖动；向左 / 右拖会播放对应方向的跑动。
- 聊天感知：通过 WorkBuddy hooks 实时同步 agent 状态（思考 / 工作中 / 完成 / 空闲）。
- 右键设置：缩放、预设比例、重置位置、聊天感知开关，偏好自动记忆。
- 系统托盘：菜单可「接入 WorkBuddy」、打开 DIY 工具、切换宠物、退出。
- DIY 管线：一张透明 PNG → 自动去背、收紧裁切、木偶动效 → 9 状态精灵图集。
- 单文件 EXE：PyInstaller 打包，无需 Python 环境，双击即用。

## 9 种动画状态 & WorkBuddy 事件映射

宠物精灵图集包含 9 个状态：idle / running-right / running-left / waving / jumping / failed / waiting / running / review。

经 hooks 接入后，自动联动：

| WorkBuddy 事件 | 宠物状态 | 气泡文案 |
|---|---|---|
| SessionStart | （启动宠物） | — |
| UserPromptSubmit | thinking（waiting） | 收到，思考中… |
| PreToolUse | thinking（waiting） | 执行工具… |
| PostToolUse | running | 工作中… |
| Stop | waving | 完成 ✓ |
| SessionEnd | idle | — |

> running-right / running-left 在拖拽时临时播放；jumping / failed / review 为可用状态，暂未绑定事件（无对应出错 / 审阅钩子）。

## 快速开始（使用者）

1. 到 **Releases** 下载 workbuddy-pet.exe。
2. 双击运行 → 桌面出现宠物，系统托盘出现图标。
3. 右键托盘图标 → 接入 WorkBuddy：自动把 hooks 写入 ~/.workbuddy/settings.json（指向本 exe，幂等、会自动清除旧版接线）。
4. 之后每次 WorkBuddy 会话开始，宠物自动启动并随状态跳动。

右键宠物本体可：退出宠物、设置 ▶（放大 / 缩小 / 预设 0.8·1.3·1.8·2.4× / 重置位置 / 聊天感知开关）。

托盘菜单：接入 WorkBuddy / 取消接入 / 打开 DIY 工具 / 选择宠物 / 退出。

### 命令行

    workbuddy-pet.exe                 # 启动（托盘 + 宠物 + 状态服务）
    workbuddy-pet.exe --state running 工作中…   # 推送一个状态
    workbuddy-pet.exe --install-hooks # 接入 WorkBuddy hooks
    workbuddy-pet.exe --uninstall-hooks
    workbuddy-pet.exe --stop          # 关闭运行中的宠物
    workbuddy-pet.exe --diy           # 打开 DIY 工具
    workbuddy-pet.exe --select        # 打开宠物选择器

## 为他人 DIY 自己的宠物

不需要写代码，给一张透明背景的静态角色图即可：

    # 方式 A：命令行
    python scripts/make_pet_from_static.py --image "my-pet.png" --slug my-pet --name "我的宠物"
    # 生成到 assets/my-pet/（atlas + pet.json），重打包 EXE 即生效

    # 方式 B：图形界面（推荐）
    python scripts/diy_gui.py

生成的资源放在 assets/<slug>/，重新运行 build.py 打包即可分发。

> 也可用程序化占位吉祥物快速试玩：python scripts/make_pet_from_static.py --make-demo --slug demo。

## 从源码构建（开发者）

    # 1. 准备环境（Windows / macOS，tkinter 自带）
    python -m venv .venv && .venv/Scripts/activate
    pip install -r requirements.txt

    # 2. 打包为单文件 EXE
    python build.py
    # 产物：dist/workbuddy-pet.exe

build.py 用 PyInstaller --onefile --windowed，并把 assets/（含 IP 熊精灵图）与 tcl/tk、pystray、PIL 一并打进 exe。

## 项目结构

| 路径 | 说明 |
|---|---|
| scripts/app.py | EXE 唯一入口：托盘 + 宠物 + 状态服务；--state/--install-hooks/--stop/--diy/--select |
| scripts/wb_pet.py | Tkinter 宠物主窗：透明、可拖拽、轮询状态、右键菜单、偏好持久化 |
| scripts/pet_daemon.py | 状态 HTTP 服务（端口 19876，POST /set {state,message}） |
| scripts/hooks_installer.py | 把 WorkBuddy hooks 写入 settings.json，幂等 + 清除旧版接线 |
| scripts/make_pet_from_static.py | DIY 管线：静态图 → 9 状态精灵图集 |
| scripts/diy_gui.py | DIY 图形界面 + 宠物选择器 |
| scripts/pet_test.py | 测试工具：cycle / 模拟 hooks / --state |
| assets/ip-bear/ | 内置示例宠物（atlas + pet.json） |
| build.py | PyInstaller 打包脚本 |

## 架构说明

- 单实例：占用本地端口 19877 作为锁，确保同一时刻只有一个宠物。
- 状态服务：app.py 起一个 127.0.0.1:19876 的 HTTP 服务，hooks 通过 exe --state <name> [msg] 推送状态（最小停留 0.3s 防抖动）。
- 偏好持久化：窗口位置、缩放、聊天感知等存于 ~/.workbuddy/wb_pet_config.json。
- PID 文件：~/.workbuddy/wb_pet.pid，用于 --stop 与单实例判断。

## 常见问题

- 宠物不随 WorkBuddy 动？确认已执行 --install-hooks，且 ~/.workbuddy/settings.json 中含 workbuddy-pet 标记的 hooks；可重新运行一次 --install-hooks 重新指向最新 exe 路径。
- 出现双宠物？安装器会自动清除 launch_wb_pet / petdex_bridge 等旧版接线，避免重复。
- 缩放冲突？滚轮缩放已从宠物本体移除，仅保留在右键「设置」菜单中，不会与页面滚动冲突。
- Linux 构建？需系统 python3-tk；其余依赖见 requirements.txt。

## License

见 LICENSE。
