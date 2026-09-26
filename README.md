# Codex Usage Widget

搭配 [OpenCodex](https://github.com/lidge-jun/opencodex) 使用的 Windows 桌面悬浮卡片，用来查看账号额度、用量和重置时间。

## 前提

- 已安装并运行 OpenCodex。
- 本程序从 OpenCodex 的本地数据中读取信息；它不代理请求，也不会上传 Token。
- 不安装补丁时，基础额度和用量信息仍可使用；“重置额度”详情可能不显示。

## 功能

- 显示池账号与主账号的额度和重置时间
- 显示日用量、限额与错误提示
- 自动刷新本地状态
- 可调整窗口大小、置顶和切换主题
- 可选显示重置额度缓存信息

## 运行

安装依赖后运行：

```powershell
pip install PySide6
python codex_usage_widget.py
```

启动 OpenCodex 后，卡片会自动读取可用的本地信息。

## 可选：OpenCodex 适配补丁

只有需要更完整的“重置额度”详情时才需要此步骤。补丁针对 OpenCodex `2.60.0` 源码；请先确认你的安装可修改源码。

1. 退出 OpenCodex。
2. 将 [`.opencodex-patch/`](.opencodex-patch/) 中的三个文件复制到 OpenCodex 源码中对应位置：
   - `reset-credit-details-cache.ts` → `src/codex/reset-credit-details-cache.ts`
   - `pool-quota-probe.ts` → `src/codex/auth-api/pool-quota-probe.ts`
   - `main-account-probe.ts` → `src/codex/auth-api/main-account-probe.ts`
3. 重新构建或重启 OpenCodex。

应用前请备份原文件。升级 OpenCodex 后，请先检查版本差异，再决定是否重新应用补丁。

## 测试

```powershell
python -m unittest -v
```

## 构建

```powershell
pip install PySide6 pyinstaller
pyinstaller --clean --noconfirm CodexUsageWidget.spec
```

构建结果位于 `dist/CodexUsageWidget.exe`。该文件仅用于本地构建，不纳入仓库。

## 许可证

本项目采用 [MIT License](LICENSE)。

`.opencodex-patch/` 中的文件基于 OpenCodex 修改，仍遵循其 MIT 许可证；完整说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
