# 贡献指南 / Contributing

## 提交前 / Before submitting

1. 阅读 [`AGENTS.md`](./AGENTS.md)、[`docs/开发维护手册.md`](./docs/开发维护手册.md) 与 [`docs/数据来源与更新.md`](./docs/数据来源与更新.md)。
2. 不提交真实 `.sav`、玩家或服务器信息、本机路径、缓存、日志、生成网页、Oodle DLL 或来源不明素材。
3. 数据变更只能从固定来源经生成器完成；不要手改大型生成文件，也不要把第三方游戏素材声明为 MIT。
4. 保持存档只读、无遥测、无远程自更新，并保持本世界库存、跨界基因与未知单位分离。

Read the project rules and maintenance/data documents first. Never submit real saves, player or server information, local paths, caches, logs, generated pages, Oodle binaries, or unlicensed assets. Preserve the read-only, offline, no-telemetry security boundary.

## 验证 / Verification

在 Windows PowerShell 运行：

```powershell
.\scripts\verify.ps1
```

UI 改动还需实际检查桌面与 390px 窄屏、四套主题、键盘焦点、空/错/忙/禁用状态和减少动态效果。说明问题时只提供从零合成的最小复现，不附真实存档。

UI changes also require real desktop and 390px checks across all four themes, keyboard focus, empty/error/busy/disabled states, and reduced motion. Use synthetic reproductions only.
