# Codex Usage Widget

一个仿 Codex/opencodex 原生风格的 Windows 桌面悬浮用量卡片，实时显示池账号用量。

## 功能

- **4 套主题可切换**：明亮模式 / 暗黑模式 / 信息面板 / 极简仪表盘
- **多账号切换**：左右箭头循环切换池账号与主账号，活动账号带标记
- **配额显示剩余用量**：5 小时窗口 + 每周窗口，低余量时变色告警
- **今日用量统计**：请求数、Tokens (in/out)、缓存 Tokens
- **窗口可缩放**：右下角拖动调整，状态自动记忆（位置/尺寸/主题/账号）
- **倒计时刷新**：配额重置时间实时倒计时

## 运行

本仓库仅包含源码，不包含编译产物。两种运行方式：

**直接运行**（需 Python 3.10+）：

```bash
pip install PySide6
python codex_usage_widget.py
```

**打包为 exe**：见下方[构建](#构建)章节，产物 `dist/CodexUsageWidget.exe` 双击运行。

运行后操作：

- 拖动：按住标题栏任意位置
- 切换主题/账号：右键菜单
- 置顶：📌 按钮
- 开机自启：将 exe 快捷方式放入 `shell:startup`

## 数据来源

通过 opencodex 本地代理自动读取 `~/.opencodex/` 目录下的：
- `codex-quota-cache.json` — 配额进度
- `config.json` — 账号池状态
- `usage.jsonl` — 今日用量

代码中零硬编码路径，数据目录通过自动发现机制获得。

## 构建

```bash
# 1. 安装依赖
pip install PySide6 pyinstaller

# 2. 打包
pyinstaller CodexUsageWidget.spec
```

输出位于 `dist/CodexUsageWidget.exe`。

## 技术栈

Python 3.14 + PySide6，PyInstaller `--onefile --windowed` 打包。

## License

MIT
