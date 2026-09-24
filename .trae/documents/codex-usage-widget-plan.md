# Codex 用量悬浮卡片实现文档

> 状态：**已交付 v6**（2026-09-25）。v5 基础上：主题切换添加 150ms 透明度渐变过渡、移除 QGraphicsDropShadowEffect、优化 _save_state 变化检测、统一 QSS 缓存。

## Context

用户通过 opencodex 本地代理（127.0.0.1:10100）让 Codex 桌面端使用 ChatGPT plus 账号池，但 Codex 桌面端是闭源应用，其原生用量 UI 绑定原生登录的 free 主账号，无法显示池账号用量（路线 A 已确认不可行）。

因此实现路线 B：一个仿 Codex/opencodex 原生风格的 Windows 桌面悬浮卡片，实时显示池账号用量。

## 数据源（只读，均位于 `~/.opencodex/`）

| 文件 | 内容 | 用途 |
|---|---|---|
| `codex-quota-cache.json` | `quotas.<accountId>`：`shortPercent`/`shortResetAt`（5h 窗）、`weeklyPercent`/`weeklyResetAt`（周窗）；主账号键为 `__main__` | 配额进度条 |
| `config.json` | `codexAccounts[]`（email/plan）、`activeCodexAccountPinned`（活动账号） | 账号池状态 |
| `usage.jsonl`（约 10MB） | 每行 JSON：`timestamp`/`provider`/`model`/`resolvedModel`/`status`/`usage.{inputTokens,outputTokens,cachedInputTokens}` | 今日用量聚合 |

注意：`quotas` 段 resetAt 为秒级时间戳，需归一化（`>1e12` 视为毫秒）。

**代码中零硬编码绝对路径**，数据目录通过自动发现机制获得（读 `widget-state.json` → `~/.opencodex` → 枚举所有用户目录 → wmic 反查代理进程 → 手动选择）。

## 技术方案

- **技术栈**：Python 3.14 + PySide6，PyInstaller `--onefile --windowed` 打包为单个自包含 exe（46.3MB），双击即用
- **开发与打包环境**：虚拟环境 `.venv/`（项目根目录下，最终产物不依赖它）
- **UI 框架**：无边框圆角卡片（`FramelessWindowHint | WindowStaysOnTopHint | Tool` + `WA_TranslucentBackground` + QSS `border-radius:12px` + `QGraphicsDropShadowEffect`），最小尺寸 280×170，可缩放

## v6 调整

- **主题切换平滑过渡**：150ms 透明度渐变（0.3→1.0 OutCubic），掩盖样式切换的视觉突兀感；实测单次切换 17-35ms 无性能瓶颈
- **移除 QGraphicsDropShadowEffect**：Qt CPU 模糊在主题切换时全窗口重算，是视觉卡顿主因之一；改用 1px 边框保持层次感
- **`_save_state` 变化检测**：状态未变化时跳过磁盘写入，消除 4-14ms 冗余 I/O
- **QSS 缓存**：`_apply_theme` 同主题重复调用时直接返回，避免重复样式重建

## v5 调整

- **light 主题更名并统一配色**：更名为"明亮模式"，配色采用原 panel 主题（浅蓝灰底 #f6f8fb、蓝色强调 #155eef），与信息面板共享同一套配色但密度不同
- **信息面板恢复常驻详情**：panel 密度 `rich` 下自动显示详情行（模型分布 Top3、失败请求数、账号索引），无需展开按钮；切换至 panel 时窗口自动扩展至 320px 高度保证完整显示
- **主题切换性能优化**：`_apply_theme` 不再调用完整 `_refresh`（避免 30s 节流外的 usage.jsonl 扫描），而是使用 `_last_snap` 缓存的快照立即更新进度条、大数字、详情行；数据层轮询（3s）独立运行，互不阻塞

## v4 调整

- **删除展开详情功能**：`▾/▴` 展开按钮和详情面板完全移除，为邮箱名称腾出空间
- **默认宽度 360→400**：保证多数字邮箱（如 `user@example.com`）在多账号切换下仍完整显示

## v3 调整

- **配额显示剩余用量**：进度条与百分比显示 `100 - 已用`，标题为"5 小时窗口剩余 / 每周窗口剩余"；极简大数字副标题"5h 剩余 / 每周剩余"
- **低余量告警色**：剩余 < 20% 红色 `#ef4444`，< 50% 橙色 `#f59e0b`，否则主题 accent 色（进度条 chunk、百分比、大数字一致变色）
- **极简主题（compact）隐藏展开按钮**：详情面板仅信息面板等 rich 密度使用（v4 中详情面板已移除，此限制失效）

## v2 功能清单

### 4 套主题可切换（右键菜单 → 主题）

| 主题 | 密度 | 说明 |
|---|---|---|
| 明亮模式 (light) | standard | 浅蓝灰底 #f6f8fb、蓝色进度条 #155eef |
| 暗黑模式 (dark) | standard | 深色 #1e1e24、青色 #2dd4bf |
| 信息面板 (panel) | rich | 与明亮模式同配色，常驻显示详情行（模型分布/失败请求/账号索引），自动扩高至 320px |
| 极简仪表盘 (minimal) | compact | 近黑底、超大百分比数字（5h 剩余 / 每周剩余），隐藏统计与进度条 |

### 交互

- ~~**点击展开详情**（v4 已移除）~~
- **多账号切换**：邮箱两侧 `‹ ›` 按钮循环切换池账号与主账号（`__main__`），仅多账号时显示；活动账号带 `●` 标记与"· 当前"后缀
- **窗口可缩放**：右下角 QSizeGrip 拖动调整，最小 280×170
- **状态记忆**：`widget-state.json` 记录位置、尺寸、主题、选中账号、数据目录
- 任意位置拖动、置顶开关（📌）、右键菜单（主题/置顶/打开 Dashboard/立即刷新/重新扫描/退出）

### 数据层

- `DataStore`：`_read_json` 带 mtime + 结果双缓存——文件未变返回缓存值；读取失败（代理写入中读到半截 JSON）回退缓存。usage.jsonl 增量读（尾部 2MB 定位今日 0 点，记录偏移量续读，30s 节流，跨天自动重置）
- `UsageStats`：聚合请求数、token in/out、缓存 tokens、失败数、按 `resolvedModel` 的模型分布
- `account_list()`：池账号（`codexAccounts`）+ 主账号（quotas 中的 `__main__` 键），活动账号排最前
- UI 3s 轮询、倒计时 1s 刷新

## Bug 修复记录（widget-data-vanish）

**症状**：启动正常显示（plus 账号、5h 7%、每周 34%），约 3 秒后变为"未知账号 / 0%"，今日统计不受影响。

**根因**：`_read_json` 的 mtime 缓存在文件未变化时返回 `None`，`snapshot()` 将其当空数据处理 → 第 2 次轮询数据消失。今日统计走独立增量读路径所以正常。

**修复**：`_read_json` 增加 `_cache` 结果缓存——mtime 未变或读取失败均返回上次成功值。经调试验证（pre/post-fix 日志对比确认），调试产物已清理。

## 交付产物

| 产物 | 路径 |
|---|---|
| 可执行文件 | `dist/CodexUsageWidget.exe`（46.3MB，自包含） |
| 源码 | `codex_usage_widget.py`（约 700 行，单文件） |
| 状态文件 | exe 同目录 `widget-state.json`（运行时自动生成） |
| 开发环境 | `.venv/`（仅开发/打包用） |

使用：双击 exe 即用；开机自启可将 exe 快捷方式放入 `shell:startup`。
