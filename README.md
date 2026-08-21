<p align="center">
  <img src="./docs/images/social-preview.png" alt="帕鲁配种图鉴 — 从手上现有的帕鲁开始算路线" width="100%" />
</p>

# 帕鲁配种图鉴

中文 · [English](./README_EN.md)

[![CI](https://img.shields.io/github/actions/workflow/status/ferretgeek/palworld-breeding-atlas/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/ferretgeek/palworld-breeding-atlas/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.10%2B-14354C?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![离线](https://img.shields.io/badge/%E7%A6%BB%E7%BA%BF-%E4%B8%8D%E8%81%94%E7%BD%91-0f766e?style=flat-square)](#隐私)
[![License](https://img.shields.io/badge/Code-MIT-6d28d9?style=flat-square)](./LICENSE)

> 网上的配种表只告诉你「A + B = C」。真正的问题是：我现在手上就这些，怎么配最快？

## 为什么会需要它

想要某只帕鲁，查配种表很容易。但表格给的是孤立的一条式子，你还得自己在脑子里往前推：C 要 A 和 B，A 我有，B 我没有，B 又要 D 和 E……推到第四层就乱了。

而且表格不知道你实际有什么。它不会告诉你"其实你笼子里那只就能直接用"，也不会告诉你"这条路要多抓一只，但另一条路一只都不用抓"。

这个工具读你自己的存档（**只读，绝不改写**），看一眼你实际拥有什么，然后给出能照着做的步骤：先配什么、第几步出什么、哪一步必须去补一只。

也可以反过来问：**我手上这些，能配出什么值得练的？**

不想连存档也完全能用——287 条图鉴和四万多条配种关系可以直接翻。

## 界面

<p align="center">
  <img src="./docs/images/atlas.png" alt="配种图鉴界面（合成数据）" width="100%" />
</p>

预览只使用内置图鉴和合成库存，不含玩家名、世界 ID、存档路径或真实服务器信息。

## 它能做什么

- **配种路线** — 最快、少补充、零补充和综合四种策略，给出可执行步骤、亲本性别，以及多条路线的并排对比。
- **反向发现** — 从现有库存出发找值得培养的新目标，结果可以固定下来比较。
- **287 条图鉴** — 按中文名、拼音、编号、属性、工作适性、战斗定位和获取方式筛选。
- **配方查询** — 亲本查子代，或目标查全部配方；特殊组合的性别限制会保留。
- **只读存档** — 自动发现 Steam 多库位置和专用服务器存档，区分本世界库存、跨世界基因和未知单位。
- **完整体验** — 深灰暗色 + 三套浅色主题、移动端固定操作栏、键盘操作、减少动效、缓存恢复，以及空 / 错 / 忙状态。

## 只想翻图鉴

```powershell
python -m http.server 8080 --directory .\src\pal_breed_helper\assets
```

打开 `http://localhost:8080`。没有注入存档时，图鉴、配方和基础配种功能都照常可用。

## 连上自己的存档

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
pal-breed-helper
```

程序完全离线、只读存档。它会从你本机合法安装的 Palworld 或 Unreal Engine 目录里寻找 `oo2core_*_win64.dll`——**仓库不分发这个 DLL**。系统里找不到时，旧的 zlib 存档仍能读取，新格式存档会给出明确提示（而不是静默失败）。

## 部署成自托管站点

`server_publish.py` 可以把指定的 `Level.sav` 解析成一套完整静态网页；源存档只读，输出走临时目录再原子发布。

```bash
export PYTHONPATH="$PWD/src"
python -m pal_breed_helper.server_publish \
  --save /srv/palworld/SaveGames/0/WORLD_ID/Level.sav \
  --output /srv/palworld-breeding-atlas/public
```

> Linux 上的新版 Oodle 存档需要兼容的 `palooz` 后端。部署建议用受限的 systemd `oneshot`，**不要常驻轮询，也不要让 Web 进程对存档目录有写权限。**
>
> 生成的页面可能含库存信息。远程访问必须放在 HTTPS 与认证反向代理之后。

完整安装、升级、备份、恢复、健康检查和卸载见 [`docs/OPERATIONS.md`](./docs/OPERATIONS.md)。

## 技术上值得一提的地方

**存档解析的每一层都有硬上限。** 存档输入体积、zlib 每一层的解压输出、导入的库存 JSON——都在解析**之前**先判上限，畸形或恶意存档打不爆内存。上限可以通过 `PAL_HELPER_MAX_SAVE_INPUT_BYTES`、`PAL_HELPER_MAX_UNCOMPRESSED_BYTES` 和 `PAL_HELPER_MAX_ZLIB_INTERMEDIATE_BYTES` 显式放宽，用于确实很大的可信存档。

**只读是真的只读。** 程序不会写回存档，也不需要游戏关闭。发布模式下源存档同样只读，输出先写临时目录再原子替换，中途失败不会留下半成品站点。

**求解器可以脱离 Python 单独回归。** 配种求解逻辑能用 Node.js 独立执行，`scripts\verify.ps1` 的门禁里包含它的回归测试，以及 287 条图鉴与配种数据的契约校验——数据改动会被立刻发现。

**数据来源是可追溯的。** 结构化输入来自 MIT 许可的 `tylercamp/palcalc` 的**指定提交**，版本、哈希和过滤规则都写在 [`docs/数据来源与更新.md`](./docs/数据来源与更新.md) 里，而不是"从某处抓的"。

## 验证

```powershell
.\scripts\verify.ps1
```

门禁包含 Python 编译与测试、287 条图鉴与配种数据契约，以及可由 Node.js 独立执行的求解器回归。

## 隐私

- 不上传存档、路径、库存、账号或日志；客户端没有遥测，也没有在线更新。
- `.sav`、运行缓存、生成的网页、崩溃日志和 Oodle DLL 全部被 Git 忽略。
- 公开截图只用内置图鉴和合成内容；CI 会拒绝提交里出现本机绝对路径、私有网段和固定世界 ID。

## 更多文档

[运维与双部署](./docs/OPERATIONS.md) · [开发维护手册](./docs/开发维护手册.md) · [数据来源与更新](./docs/数据来源与更新.md) · [变更记录](./CHANGELOG.md) · [参与贡献](./CONTRIBUTING.md) · [安全策略](./SECURITY.md)

## 技术栈

`Python` · `Tkinter` · `HTML` · `CSS` · `JavaScript` · `PyInstaller` · `systemd`（可选）

## 数据与许可

- 原创程序代码使用 [MIT License](./LICENSE)。
- 固定结构化输入来自 MIT 许可的 `tylercamp/palcalc` 指定提交，详见 [`docs/数据来源与更新.md`](./docs/数据来源与更新.md)。
- **Palworld 名称、角色图标与游戏数据不在 MIT 授权范围内**，具体边界见 [`THIRD_PARTY_NOTICES.md`](./THIRD_PARTY_NOTICES.md)。
- `oo2core_*_win64.dll` 明确忽略，不会提交。

非官方、非商业社区项目，与 Pocketpair 没有隶属、授权或背书关系。
