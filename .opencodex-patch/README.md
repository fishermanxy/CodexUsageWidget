# OpenCodex 适配说明

此目录保存对本机 OpenCodex `2.60.0` 安装目录的审计副本和回滚材料，不是小组件源码，也不属于 EXE 运行时依赖。

## JSON 缓存来源

`%USERPROFILE%\.opencodex\reset-credit-details-cache.json` 是运行时产物。它不会预置在本项目、OpenCodex 包或 EXE 中，也不能手动创建后当作有效详情。只有 OpenCodex 成功执行详情同步后才会生成。

## 原版与人工修改的差异

- `original/reset-credit-details-cache.ts` 证明 OpenCodex 2.60.0 原本已有详情 HTTPS 请求、脱敏缓存结构和原子写入逻辑。
- 原版 `pool-quota-probe.ts`、`main-account-probe.ts` 没有导入或调用该模块，所以原版流程不会执行它、不会产生 JSON。
- 项目在两个探针的正常 `wham/usage` 配额刷新成功路径中接入详情同步；同时支持同账号并发合并，只有“数量相同且明细完整”才跳过详情请求，空或不完整明细会在下一次正常配额刷新时重试。
- 详情接口是 `https://chatgpt.com/backend-api/wham/rate-limit-reset-credits`，不是本地端口；普通配额接口是 `https://chatgpt.com/backend-api/wham/usage`。

## 发布与回滚

本目录保存项目使用的第三方源码副本和适配材料，并随源码发布；不要把它或运行时 JSON 缓存打进 EXE 或仅含运行文件的压缩包。第三方归属与许可证见项目根目录的 [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md)。升级 OpenCodex 后，先比较原版模块和两个调用点；需要回滚时，用 `original/` 下同名文件恢复安装目录，然后执行 `ocx restart`。
