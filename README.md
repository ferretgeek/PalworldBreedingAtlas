<p align="center">
  <img src="./docs/images/social-preview.png" alt="Palworld Breeding Atlas preview / 帕鲁配种图鉴预览" width="100%" />
</p>

# Palworld Breeding Atlas — 幻兽帕鲁配种规划与图鉴 / Palworld Breeding Planner & Atlas

[![CI](https://img.shields.io/github/actions/workflow/status/ferretgeek/PalworldBreedingAtlas/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/ferretgeek/PalworldBreedingAtlas/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.10%2B-14354C?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Offline](https://img.shields.io/badge/Local--first-offline-0f766e?style=flat-square)](#隐私--privacy)
[![License](https://img.shields.io/badge/Code-MIT-6d28d9?style=flat-square)](./LICENSE)

**把 287 只帕鲁、四万余条配种关系和自己的存档，收进一张真正能走通的路线图。**

这是一个本地优先的 Palworld 配种规划、图鉴与只读存档工具。Windows 启动器自动发现 Steam 存档，浏览器界面提供路线规划、反向发现、图鉴、配方、收藏与状态恢复；同一套静态资源也可以部署到自托管服务器，按需读取最新存档。

**A local-first breeding planner, atlas, and read-only save companion for Palworld.** It combines route planning, reverse discovery, a searchable Paldeck, recipe lookup, favorites, responsive themes, and optional self-hosted save publishing.

> 非官方、非商业社区项目，与 Pocketpair 没有隶属、授权或背书关系。Palworld 名称、数据和视觉资产归其权利人所有。 / Unofficial, non-commercial community project. Not affiliated with or endorsed by Pocketpair.

## 界面 / Interface

<p align="center">
  <img src="./docs/images/atlas.png" alt="Palworld Breeding Atlas synthetic interface / 帕鲁配种图鉴合成界面" width="100%" />
</p>

预览仅使用内置图鉴和合成库存，不含玩家名、世界 ID、存档路径或真实服务器信息。 / The preview uses bundled atlas data and synthetic inventory only—no player name, world ID, save path, or real server information.

## 能做什么 / What it does

- **配种路线 / Breeding routes** — 最快、少补充、零补充与综合策略，提供可执行步骤、亲本性别和多路线对比。
- **反向发现 / Reverse discovery** — 从已有库存出发，寻找值得培养的新目标，并固定结果比较。
- **287 条图鉴 / 287-entry Paldeck** — 中文、拼音、编号、属性、工作适性、战斗定位与获取方式筛选。
- **配方工具 / Recipe tools** — 亲本查子代、目标查全部配方，保留特殊组合的性别限制。
- **只读存档 / Read-only saves** — 发现 Steam 多库与专用服务器存档，区分本世界库存、跨界基因与未知单位。
- **细致体验 / Polished experience** — 深灰暗色与三套完整浅色主题、移动端固定操作、键盘、减少动态效果、缓存恢复、空错忙状态。

## 直接看图鉴 / Browse without a save

```powershell
python -m http.server 8080 --directory .\src\pal_breed_helper\assets
```

打开 `http://localhost:8080`。没有注入存档时仍可使用图鉴、配方和基础配种能力。

Open `http://localhost:8080`. The atlas and recipe tools remain available without an injected save.

## 运行 Windows 启动器 / Run the Windows launcher

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
pal-breed-helper
```

程序完全离线、只读存档，并会从本机合法安装的 Palworld 或 Unreal Engine 目录寻找 `oo2core_*_win64.dll`。仓库不分发 Oodle DLL；如果系统找不到，旧 zlib 存档仍可读取，新格式存档会给出明确提示。

The app is offline and read-only. It discovers `oo2core_*_win64.dll` from a lawful local Palworld or Unreal Engine installation. The proprietary Oodle DLL is not distributed in this repository.

## 自托管发布 / Self-hosted publishing

`server_publish.py` 可以把指定的 `Level.sav` 解析为完整静态网页包；源存档只读，输出使用临时目录和原子发布。

```bash
export PYTHONPATH="$PWD/src"
python -m pal_breed_helper.server_publish \
  --save /srv/palworld/SaveGames/0/WORLD_ID/Level.sav \
  --output /srv/palworld-breeding-atlas/public
```

Linux 的新版 Oodle 存档需要兼容的 `palooz` 后端。部署时建议使用受限的 systemd `oneshot`，不要常驻轮询，也不要把存档目录开放给 Web 进程写入。

New-format Oodle saves on Linux require a compatible `palooz` backend. Use a restricted systemd `oneshot`; do not poll continuously or grant the web process write access to saves.

生成页可能含库存信息。远程访问必须放在 HTTPS 与认证反向代理之后；完整安装、升级、备份、恢复、健康检查和卸载步骤见 [`docs/OPERATIONS.md`](./docs/OPERATIONS.md)。

Generated pages can contain inventory data. Put remote access behind HTTPS and an authenticated reverse proxy. See [`docs/OPERATIONS.md`](./docs/OPERATIONS.md) for installation, upgrades, backup, restore, health checks, and removal.

## 验证 / Verification

```powershell
.\scripts\verify.ps1
```

门禁包含 Python 编译与测试、287 条图鉴和配种数据契约，以及可由 Node.js 独立执行的求解器回归。

The gate covers Python compilation and tests, the 287-entry data contract, and solver regression runnable independently with Node.js.

## 文档 / Documentation

- [运维与双部署 / Operations and dual deployment](./docs/OPERATIONS.md)
- [开发维护手册 / Development handbook](./docs/开发维护手册.md)
- [数据来源与更新 / Data provenance and updates](./docs/数据来源与更新.md)
- [安全策略 / Security policy](./SECURITY.md)
- [贡献指南 / Contributing](./CONTRIBUTING.md)
- [变更记录 / Changelog](./CHANGELOG.md)

## 数据与许可 / Data and licensing

- 原创程序代码使用 [MIT License](./LICENSE)。
- 固定结构化输入来自 MIT 许可的 `tylercamp/palcalc` 指定提交，版本、哈希和过滤规则见 [`docs/数据来源与更新.md`](./docs/数据来源与更新.md)。
- Palworld 名称、角色图标与游戏数据不属于 MIT 授权范围；具体边界见 [`THIRD_PARTY_NOTICES.md`](./THIRD_PARTY_NOTICES.md)。
- `oo2core_*_win64.dll` 明确忽略且不会提交。

Original source code is MIT-licensed. Palworld names, character images, game data, and Oodle are not covered by that license; see [`THIRD_PARTY_NOTICES.md`](./THIRD_PARTY_NOTICES.md).

## 隐私 / Privacy

- 不上传存档、路径、库存、账号或日志；客户端没有遥测和在线更新。
- `.sav`、运行缓存、生成网页、崩溃日志与 Oodle DLL 均被 Git 忽略。
- 公开截图只使用内置图鉴与合成内容；提交前 CI 会拒绝本机绝对路径、私有网段和固定世界 ID。

No saves, paths, inventory, accounts, or logs are uploaded. There is no telemetry or runtime updater. Public previews use synthetic inventory only.

## 技术 / Stack

`Python` · `Tkinter` · `HTML` · `CSS` · `JavaScript` · `PyInstaller` · `systemd (optional)`
