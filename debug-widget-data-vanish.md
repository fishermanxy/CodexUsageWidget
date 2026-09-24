# Debug: widget-data-vanish

状态：[WAITING-CONFIRM]

## 症状
CodexUsageWidget.exe 启动时正常显示（plus 账号、5h 7%、每周 34%），约 3 秒后变为"未知账号 / 0% / 0%"；今日统计保持正常。

## 假设与验证
- **H1 ✅ 确认**：`_read_json` mtime 缓存语义错误——文件未变返回 `None`，`snapshot()` 将其当空数据，导致第 2 次轮询（3s 后）数据消失
- H2 ❌ 排除：无解析异常日志
- H3 ❌ 排除：`active_id` 与账号键完全匹配
- H4 ❌ 排除：无重复发现触发
- H5 ✅ 佐证：今日统计走独立增量读路径，不受影响

## 证据（Pre-fix 日志）
- t+0s：`read ok`，`quota_is_none: false` → 正常
- t+3s：`mtime unchanged -> return None` ×2，`quota_is_none: true`，`active_id: ""` → 异常

## 修复
`_read_json` 保留上次成功读取的缓存：mtime 未变时返回缓存；读取失败（代理写入中）也回退缓存。

## Post-fix 日志
- t+3s / t+6s：`quota_is_none: false`，`cached: true`，`active_id` 正常 ✅

## 待办
- [ ] 用户确认 exe 修复效果
