# 第三方内容说明 / Third-party notices

## 原创代码 / Original code

本仓库的原创 Python、HTML、CSS、JavaScript、测试和文档代码使用 MIT License。MIT 不自动覆盖下面列出的第三方内容。

Original Python, HTML, CSS, JavaScript, tests, and documentation code in this repository are MIT-licensed. That license does not automatically cover the third-party material below.

## Palworld

Palworld、Pocketpair、角色名称、角色图标和相关游戏数据归各自权利人所有。仓库是非官方、非商业的爱好者工具，不得暗示官方身份或背书。相关视觉内容仅用于帮助合法拥有游戏的玩家理解自己的存档与配种关系，并不授予再次商业化或独立再许可的权利。

Palworld, Pocketpair, character names, character images, and related game data remain the property of their respective rights holders. This is an unofficial, non-commercial fan utility and must not imply official status or endorsement. Included visual material is not sublicensed for independent commercial reuse.

参考 / Reference: [Pocketpair 二次创作指南](https://www.pocketpair.jp/guidelines-derivativework?lang=zh)

## 结构化数据 / Structured data

配种与基础图鉴的结构化主输入固定到 [`tylercamp/palcalc`](https://github.com/tylercamp/palcalc) 的指定提交；上游项目使用 MIT License。固定提交、输入哈希、过滤规则与生成结果见 `src/pal_breed_helper/assets/data/provenance.json` 和 `docs/数据来源与更新.md`。

The structured breeding source is pinned to a specific commit of [`tylercamp/palcalc`](https://github.com/tylercamp/palcalc), which is MIT-licensed. The exact commit, hashes, filters, and generated outputs are recorded in the provenance files.

## Oodle

`oo2core_*_win64.dll` 是专有组件，不在本仓库中分发，也不属于 MIT License。Windows 客户端只会从用户本机合法安装的 Palworld 或 Unreal Engine 中发现它；维护者不得把该 DLL 加回 Git 历史、Release 或安装包。

`oo2core_*_win64.dll` is proprietary. It is not distributed here and is not covered by the MIT License. The Windows client only discovers it from the user's lawful local installation. Do not add the DLL to Git history, releases, or packages.
