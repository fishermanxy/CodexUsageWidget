# Codex Usage Widget

一个仿 Codex/opencodex 原生风格的 Windows 桌面悬浮用量卡片，实时显示池账号用量。

## 功能

- **4 套主题可切换**：明亮模式 / 暗黑模式 / 信息面板 / 极简仪表盘
- **多账号切换**：左右箭头循环切换池账号与主账号，活动账号带标记
- **按账号统计今日用量**：池账号与主账号分别统计请求、Tokens 和错误数
- **配额显示剩余用量**：5 小时窗口 + 每周窗口，低余量时变色告警；free 账号显示“无额度”
- **自动刷新**：监听 OpenCodex 数据文件变化，避免固定轮询造成延迟和无效读取
- **重置额度**：摘要分开显示可用次数与最早到期；存在安全详情缓存时可展开查看逐张日期和剩余时间
- **今日用量统计**：请求数、Tokens (in/out)、缓存 Tokens
- **窗口可缩放**：右下角拖动调整，状态自动记忆（位置/尺寸/主题/账号）
- **倒计时刷新**：启动、账号切换或配额文件更新后立即显示重置倒计时，后续仅用本地时间自动刷新

### 重置额度缓存机制

小组件只读 OpenCodex 写入的 `reset-credit-details-cache.json`，不会保存、读取或使用令牌，也不会提供消耗额度的按钮。缓存按账号保存以下脱敏字段：

- `schemaVersion`、`producerVersion`、递增的 `revision`
- 账号对应的 `availableCount`
- 每张额度的 `grantedAt`（如果上游提供）和绝对 `expiresAt`
- `updatedAt`；查询失败时保留 `lastFailureAt` 和上一次有效明细

OpenCodex 只在正常配额刷新成功后，账号首次没有完整有效详情缓存或发现 `resetCredits` 数量变化时查询一次官方只读详情接口。只有数量相同且缓存中每张额度都有对应详情时才跳过请求；明细为空、缺失或数量不一致时，下一次正常配额刷新会重试。小组件不会为了更新倒计时向 OpenCodex 或上游发请求；它根据绝对到期时间在本地计算显示，并在文件变更后即时重新读取。官方 Codex 等外部界面的消费，要等 OpenCodex 下一次正常配额刷新观察到数量变化后才会同步，界面显示的“最近同步”时间就是这份缓存的确认时刻。

查询失败不会影响代理或普通配额刷新：界面保留上次有效明细并显示失败时间；如果没有可用明细，则只显示数量和“到期信息暂不可用”。缓存数量与普通配额不一致时，小组件保留普通配额次数并提示详情待同步，不把旧缓存当作当前额度。缓存采用临时文件替换写入，避免小组件读到半个 JSON 文件。

额度摘要使用两行信息：第一行显示可用次数，第二行显示最早到期日期和剩余时间。展开后，每张额度都有独立的编号、到期日期与剩余时间行；窗口会按实际详情高度提高最小高度，因此已保存的窄窗口也不会压缩或重叠文本。

### 文件来源与启用边界

`reset-credit-details-cache.json` 是运行时产物，不是本仓库的源码文件，也不应手动创建、提交、打包或随 EXE 分发。它仅在已修改的 OpenCodex 首次执行额度详情同步后，才会在 `%USERPROFILE%\.opencodex\` 中生成；没有生成时，小组件只显示普通配额中的额度数量并降级显示“到期信息暂不可用”。

核对 OpenCodex `2.60.0` 的原始备份可知：`src/codex/reset-credit-details-cache.ts` 原本已经存在，内部已包含详情 HTTPS 请求、脱敏 JSON 序列化和临时文件替换写入；但原版 `pool-quota-probe.ts` 与 `main-account-probe.ts` 没有导入或调用该模块。因此原版进程不会执行它，也就不会产生 JSON。

本轮人工修改的是 OpenCodex 的安装目录源码，而不是手工写入 JSON：在两个配额探针完成既有配额刷新后调用该模块，并补强同账号并发合并及“数量未变化时不重复请求”的条件。由此把原有但未接通的模块接入运行路径。

这里涉及的是两个 ChatGPT 后端 HTTPS 接口，不是本机监听端口：既有的 `https://chatgpt.com/backend-api/wham/usage` 返回普通配额及重置额度总数；详情接口 `https://chatgpt.com/backend-api/wham/rate-limit-reset-credits` 返回逐张额度的到期时间。小组件不开放端口，也不直接请求任一接口。

源码没有作者注释或发布说明解释该模块为何未接通，不能把原因当作已证实事实。技术上合理的推断是：逐张到期信息会额外发起带账号凭据的请求、依赖未公开的响应契约，并增加持久化元数据与失败处理的维护面，因此可能是未完成或尚未正式启用的功能。当前补丁将其限定为辅助信息：请求失败不会影响代理、普通配额或路由。

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
- `reset-credit-details-cache.json`（可选）— 重置额度的安全详情缓存

代码中零硬编码路径，数据目录通过自动发现机制获得。

## OpenCodex 接线升级与回滚

本轮为 OpenCodex `2.60.0` 的本机安装启用了原本未接通的重置额度详情缓存模块，并补强其同步条件。升级 OpenCodex 后，应先确认模块与两个调用点仍存在，再重新验证缓存格式与服务启动：

- `src/codex/reset-credit-details-cache.ts`
- `src/codex/auth-api/pool-quota-probe.ts`
- `src/codex/auth-api/main-account-probe.ts`

如果新版 OpenCodex 改动了相关接口或缓存契约，先暂停使用补丁，保留小组件的“数量可见、到期详情不可用”降级行为；不要把令牌复制到缓存或发布包。回滚时，用项目内 `.opencodex-patch/original/` 中对应的原始备份恢复安装目录的三个文件，然后重启 OpenCodex 并确认代理恢复。`.opencodex-patch/` 是随源码发布的第三方补丁材料，不应打进 EXE 或仅含运行文件的发布压缩包。

## 本轮源码修改清单

以下是本轮实际修改的源码和构建文件；`.opencodex-patch/` 中的 TypeScript 是 OpenCodex 源码的复制和修改版，不属于小组件 EXE 的运行时文件。第三方归属与许可证见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

### 小组件项目

| 文件 | 修改内容 |
| --- | --- |
| codex_usage_widget.py | 移除 3 秒固定轮询，改为 QFileSystemWatcher 监听配额、配置、用量日志和重置额度缓存；加入 250ms 防抖、目录监听和 5 分钟监视器健康检查。 |
| codex_usage_widget.py | 用量日志最多 30 秒合并扫描，并处理原子替换、同大小重写、截断和无效 JSON；统计按当前账号隔离，兼容 openai 与 openai-&lt;账号标签&gt;。 |
| codex_usage_widget.py | 增加重置额度脱敏缓存读取、账号与数量匹配、版本兼容提示、最近同步/失败状态；摘要分离次数和最早到期，展开详情采用固定行高，并按实际内容自动提高窗口最小高度。 |
| codex_usage_widget.py | 增加本地倒计时调度：超过 1 天按天、1 天内按小时、1 小时内按分钟、最后 1 分钟按秒；设置新配额后立即刷新标签，极简主题显示 5 小时和每周倒计时；free 账号两类标准额度显示“无额度”。 |
| test_widget_data.py | 新增数据层和界面状态测试，覆盖账号筛选、主账号、跨日和无效日志、日志重写、缓存回退、周期倒计时、立即倒计时更新、free 账号无额度显示、付费账号恢复，以及重置额度的账号/数量隔离和完整性校验。 |
| CodexUsageWidget.spec | 为 PyInstaller one-file 构建加载 PySide6 DLL runtime hook；将 shiboken6 DLL 放到 PySide6 目录，并过滤外部 ICU、API-set 和 UCRT DLL。 |
| pyside6_dll_path.py | 新增运行时 hook，将 one-file 解压目录中的 PySide6 和 shiboken6 DLL 目录注册到 Windows 搜索路径，修复打包后 QtCore DLL 加载失败。 |
| README.md | 记录本轮源码修改、缓存契约、触发条件、升级检查和回滚边界。 |

### 本机 OpenCodex 2.60.0 接线

| 文件 | 修改内容 |
| --- | --- |
| src/codex/reset-credit-details-cache.ts | OpenCodex 2.60.0 原本已有但未接通的模块；原始代码已定义详情 HTTPS 请求、脱敏缓存格式和临时文件替换写入。 |
| src/codex/reset-credit-details-cache.ts | 本轮修改同账号并发合并、数量相同且明细完整时跳过请求、空或不完整明细在下一次正常配额刷新时重试、零额度时避免无意义写入，并以既有 usage 响应的数量作为缓存匹配键。 |
| src/codex/auth-api/pool-quota-probe.ts | 池账号完成正常配额解析后接入详情缓存同步。 |
| src/codex/auth-api/main-account-probe.ts | 主账号接入同一同步路径，并用实际账号身份隔离详情。 |

OpenCodex 接线文件的原始版本和补丁副本保存在 `.opencodex-patch/`，随源码发布用于升级核对和回滚，但不应打进 EXE 或仅含运行文件的发布压缩包。JSON 缓存则是运行时产物，不在项目目录或发布物中。

## 测试

```bash
python -m unittest -v
```

打包后的 EXE 验收：双击 `dist/CodexUsageWidget.exe` 后，确认进程持续运行且未出现 `DLL load failed while importing QtCore` 对话框。

### 本机构建记录（2026-09-26）

- 构建命令：`.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean CodexUsageWidget.spec`
- 产物：`dist/CodexUsageWidget.exe`，49,092,494 bytes
- SHA-256：`2418FE3E3E41C2A9F00D08018F14E60DCEC2A2611C403B43AB6A8FDD656E73F3`
- 验证：Python 语法检查和 14 项单元测试通过，PyInstaller 清理式构建成功；本次同步未再次启动 EXE 做人工界面验收。

这份产物来自 `main` 的未提交工作树，仅表示本机构建完成，尚未作为正式发布版本；最新版 EXE 的人工启动验收仍待完成。

## 构建

```bash
# 1. 安装依赖
pip install PySide6 pyinstaller

# 2. 打包
pyinstaller CodexUsageWidget.spec
```

输出位于 `dist/CodexUsageWidget.exe`。

`CodexUsageWidget.spec` 会加载 `pyside6_dll_path.py`。该运行时 hook 会在 one-file EXE 解压后，同时将 PySide6 和 shiboken6 的 DLL 目录加入 Windows DLL 搜索路径；`QtCore.pyd` 依赖位于 shiboken6 目录中的 `shiboken6.abi3.dll`，两者都注册后可避免导入 QtCore 时出现“找不到指定的程序”。spec 同时过滤构建环境可能带入的外部 ICU、API-set 和 UCRT DLL，避免它们覆盖 Qt6Core 需要的 Windows ICU 接口。

### 打包后 QtCore 启动错误排查

如果 EXE 弹出 `DLL load failed while importing QtCore`，或 Windows 提示 `无法定位程序输入点 ucnv_open`，先确认使用的是最新构建产物，并重新执行：

```bash
pyinstaller --clean --noconfirm CodexUsageWidget.spec
```

这类错误通常来自构建环境的 DLL 污染：Poppler 可能通过 `PATH` 提供 ICU DLL，外部 `icuuc.dll` 导出的入口是 `ucnv_open_78`，而当前 Qt6Core 需要未带版本后缀的 `ucnv_open`。`CodexUsageWidget.spec` 会过滤 `icu*`、`api-ms-win-*`、`ext-ms-win-*` 和 `ucrtbase.dll`，避免这些文件覆盖 Windows 的匹配实现；同时把 `shiboken6.abi3.dll` 放在 `PySide6` 目录，降低 QtCore 的跨目录依赖。

发布前应在干净环境验证，不要只依据“进程仍存在”判断成功。Windows PowerShell 可使用以下检查确认产物身份：

```powershell
Get-FileHash .\dist\CodexUsageWidget.exe -Algorithm SHA256
```

随后双击该路径下的 EXE，确认窗口显示为 `Codex Usage Widget`，且没有 `Unhandled exception in script` 或 QtCore DLL 对话框。旧目录中的同名 EXE 不会自动更新。

## 技术栈

Python 3.14 + PySide6，PyInstaller `--onefile --windowed` 打包。

## License

本项目原创代码采用 MIT License，版权归 `fishermanxy`。仓库中的 OpenCodex 复制和修改文件保留其上游版权与 MIT License，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
