# 运维与双部署 / Operations and dual deployment

## 架构 / Architecture

- Windows 启动器只读发现并解析 `Level.sav`，把结果写入用户数据目录中的隔离网页包；浏览器 UI 不需要后端。
- 服务器入口 `pal_breed_helper.server_publish` 对指定存档做一次稳定读取，再原子替换静态输出；Web 服务器只需读取输出目录，不应读取或写入存档目录。
- 两种模式共用解析器、数据契约和静态资源。原始存档始终是外部只读输入，不属于本项目备份。

The Windows launcher and the server publisher share the same parser, data contract, and static UI. The server command performs one stable read and atomically replaces a static output bundle. Saves remain external, read-only inputs.

## 本地安装与配置 / Local installation and configuration

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
pal-breed-helper
```

默认数据目录是 `%LOCALAPPDATA%\PalBreedHelper`；测试或便携部署可显式设置 `PAL_BREED_HELPER_DATA_DIR`。可用 `PALWORLD_SAVE_ROOT` 增加一个存档扫描根目录。不要把公开仓库目录或 Web 根目录设为用户数据目录。

The default data directory is `%LOCALAPPDATA%\PalBreedHelper`. `PAL_BREED_HELPER_DATA_DIR` can override it, and `PALWORLD_SAVE_ROOT` can add one save-search root. Do not use the repository or a public web root as the private data directory.

## 服务器部署 / Server deployment

在仅对存档有读取权限的账号下运行：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
export PYTHONPATH="$PWD/src"
python -m pal_breed_helper.server_publish \
  --save /srv/palworld/SaveGames/0/WORLD_ID/Level.sav \
  --output /srv/palworld-breeding-atlas/public
```

把命令交给受限的 `systemd` oneshot/timer 或等价调度器；不要启动高频常驻轮询。新版 Oodle 存档在 Linux 需要兼容的 `palooz` 后端。输出可能包含库存，因此 Web 服务应只读输出目录，并在非本机访问时使用 HTTPS、认证与合理限流；项目本身不提供登录层。

Run this as a restricted account through a `systemd` oneshot/timer or equivalent scheduler, not a high-frequency daemon. New Oodle saves need a compatible `palooz` backend on Linux. The output can reveal inventory; serve it read-only behind HTTPS, authentication, and rate limits. This project does not provide an authentication layer.

## 升级与回滚 / Upgrade and rollback

1. 保留当前源码版本和用户数据目录快照。
2. 在新虚拟环境安装目标版本并运行 `scripts/verify.ps1`（Windows）或等价的 Python/Node 门禁。
3. 服务器先发布到新的私有输出目录，检查 `server-status.json` 与页面后再切换 Web 根目录。
4. 回滚时恢复旧源码/虚拟环境和旧输出目录；无需修改原始存档。

Keep the previous source, virtual environment, data snapshot, and static output. Validate the new version and publish to a separate private directory before switching the web root. Rollback only restores those artifacts; it never modifies saves.

## 备份与恢复 / Backup and restore

- 本地：退出程序后复制 `%LOCALAPPDATA%\PalBreedHelper`（或自定义数据目录）。恢复时先安装相同或更新版本，再把备份复制回同一路径。
- 服务器：静态输出可从存档重建；若保留发布状态或 Web 配置，备份整个私有输出目录和反向代理配置。Palworld 自身存档必须按游戏服务器的独立流程备份。
- 恢复后启动程序或强制重新发布，并确认页面中的来源时间、数量和 `fresh` 状态符合预期。

For local restore, stop the app and copy the data directory back after installing the same or a newer version. Server output is rebuildable; back it up only with deployment configuration if desired. Back up Palworld saves through the game server's own procedure.

## 健康检查与排错 / Health checks and troubleshooting

- 本地：运行 `.\scripts\verify.ps1`，再确认启动器能发现存档、生成网页并打开四套主题。
- 服务器：确认 `index.html`、图标和 `server-status.json` 可读；`busy` 应最终为 `false`、`lastError` 为空、`fresh` 为 `true`。若 `fresh=false`，存档在解析期间发生变化，应重新执行发布。
- 新格式存档提示缺少 Oodle：Windows 需合法本机游戏 DLL；Linux 需兼容 `palooz` 后端。仓库不会分发 DLL。
- 页面旧样式或图标：清理反向代理/CDN 缓存并确认 HTML 引用的带版本资源和相对图标 URL 均返回 200。
- 找不到存档：显式传入 `--save`，或本地设置 `PALWORLD_SAVE_ROOT`；不要放宽目录写权限。

Check that `busy` settles to `false`, `lastError` is empty, and `fresh` is `true`. A false `fresh` value means the save changed during parsing and should be republished. Missing Oodle support, stale caches, or an incorrect save path should be fixed without granting write access to saves.

## 卸载 / Uninstall

本地先退出程序，删除虚拟环境或已安装包；只有确认不再需要收藏、配置和生成结果时，才删除 `%LOCALAPPDATA%\PalBreedHelper`。服务器先停用调度器与 Web 站点，再删除项目虚拟环境和静态输出；不要删除 Palworld 存档目录。

Stop the app or server schedule first, remove the virtual environment/package and static output, and delete the local data directory only if its settings and generated results are no longer needed. Never remove the Palworld save directory as part of uninstalling this project.
