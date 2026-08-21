<p align="center">
  <img src="./docs/images/social-preview.png" alt="Palworld breeding atlas — routes from the Pals you already own" width="100%" />
</p>

# Palworld breeding atlas

[中文](./README.md) · English

[![CI](https://img.shields.io/github/actions/workflow/status/ferretgeek/palworld-breeding-atlas/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/ferretgeek/palworld-breeding-atlas/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.10%2B-14354C?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Offline](https://img.shields.io/badge/offline-local--first-0f766e?style=flat-square)](#privacy)
[![License](https://img.shields.io/badge/Code-MIT-6d28d9?style=flat-square)](./LICENSE)

> Every breeding chart online tells you "A + B = C." The question you actually have is: given what's in my base right now, what's the fastest path?

## Why this exists

Looking up a single breeding pair is easy. But a chart gives you one isolated equation, and you have to walk backwards yourself: C needs A and B; I have A; B needs D and E; D needs… by the fourth layer you've lost track.

Charts also don't know what you own. They won't tell you that the Pal already in your pen works, and they won't tell you that one route needs a trip out to catch something while another needs none.

This reads your own save (**read-only, never writes**), sees what you actually have, and gives you steps you can follow: breed this, then this, and here's the one point where you need to go catch a missing parent.

You can also ask it backwards: **from what I own, what's worth working toward?**

And it's fully usable with no save at all — the 287-entry Paldeck and forty-thousand-plus breeding relationships are browsable on their own.

## Interface

<p align="center">
  <img src="./docs/images/atlas.png" alt="Breeding atlas interface with synthetic data" width="100%" />
</p>

The preview uses bundled atlas data and synthetic inventory only — no player name, world ID, save path, or real server information.

## What it does

- **Breeding routes** — fastest, fewest additions, zero additions, and balanced strategies, with executable steps, parent genders, and side-by-side route comparison.
- **Reverse discovery** — start from your current inventory to find new targets worth pursuing, and pin results to compare.
- **287-entry Paldeck** — filter by name, pinyin, number, element, work suitability, combat role, and how it's obtained.
- **Recipe lookup** — parents to offspring, or target to every recipe, preserving the gender restrictions on special combinations.
- **Read-only saves** — auto-discovers Steam multi-library locations and dedicated-server saves, distinguishing in-world inventory, cross-world genes, and unknown units.
- **A finished experience** — deep-gray dark mode plus three light themes, pinned mobile controls, keyboard operation, reduced motion, cached restore, and real empty / error / busy states.

## Just browse the atlas

```powershell
python -m http.server 8080 --directory .\src\pal_breed_helper\assets
```

Open `http://localhost:8080`. Without an injected save, the atlas, recipes, and basic breeding tools still work.

## Connect your own save

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
pal-breed-helper
```

The app is fully offline and opens saves read-only. It looks for `oo2core_*_win64.dll` in a lawful local Palworld or Unreal Engine installation — **this repository does not distribute that DLL.** When it isn't found, older zlib saves still load and newer formats produce a clear message rather than a silent failure.

## Publish as a self-hosted site

`server_publish.py` turns a given `Level.sav` into a complete static site. The source save is read-only, and output goes through a temp directory with an atomic publish.

```bash
export PYTHONPATH="$PWD/src"
python -m pal_breed_helper.server_publish \
  --save /srv/palworld/SaveGames/0/WORLD_ID/Level.sav \
  --output /srv/palworld-breeding-atlas/public
```

> New-format Oodle saves on Linux need a compatible `palooz` backend. Deploy as a restricted systemd `oneshot`. **Don't poll continuously, and don't grant the web process write access to the save directory.**
>
> Generated pages can contain inventory data. Put remote access behind HTTPS and an authenticated reverse proxy.

Installation, upgrades, backup, restore, health checks, and removal are documented in [`docs/OPERATIONS.md`](./docs/OPERATIONS.md).

## Worth noting technically

**Every layer of save parsing has a hard ceiling.** Save input size, each zlib layer's decompressed output, and imported inventory JSON are all bounded **before** parsing, so a malformed or hostile save can't exhaust memory. The limits can be raised explicitly via `PAL_HELPER_MAX_SAVE_INPUT_BYTES`, `PAL_HELPER_MAX_UNCOMPRESSED_BYTES`, and `PAL_HELPER_MAX_ZLIB_INTERMEDIATE_BYTES` for genuinely large trusted saves.

**Read-only means read-only.** The app never writes back to a save and doesn't require the game to be closed. In publish mode the source save is likewise read-only, with output written to a temp directory and swapped atomically, so a mid-run failure never leaves a half-built site.

**The solver can be regression-tested without Python.** The breeding solver runs standalone under Node.js, and `scripts\verify.ps1` gates on both that regression suite and a data contract covering the 287 atlas entries and breeding relationships — so a data change is caught immediately.

**Data provenance is traceable.** Structured inputs come from a **pinned commit** of the MIT-licensed `tylercamp/palcalc`, with version, hashes, and filtering rules recorded in [`docs/数据来源与更新.md`](./docs/数据来源与更新.md) rather than "scraped from somewhere."

## Verification

```powershell
.\scripts\verify.ps1
```

The gate covers Python compilation and tests, the 287-entry data contract, and solver regression runnable independently with Node.js.

## Privacy

- No saves, paths, inventory, accounts, or logs are uploaded. No telemetry, no runtime updater.
- `.sav` files, runtime caches, generated pages, crash logs, and the Oodle DLL are all git-ignored.
- Public screenshots use bundled atlas data and synthetic content only; CI rejects commits containing local absolute paths, private network ranges, or fixed world IDs.

## More documentation

[Operations and dual deployment](./docs/OPERATIONS.md) · [Development handbook](./docs/开发维护手册.md) · [Data provenance](./docs/数据来源与更新.md) · [Changelog](./CHANGELOG.md) · [Contributing](./CONTRIBUTING.md) · [Security policy](./SECURITY.md)

## Stack

`Python` · `Tkinter` · `HTML` · `CSS` · `JavaScript` · `PyInstaller` · `systemd` (optional)

## Data and licensing

- Original source code is under the [MIT License](./LICENSE).
- Pinned structured inputs come from a specified commit of the MIT-licensed `tylercamp/palcalc`; see [`docs/数据来源与更新.md`](./docs/数据来源与更新.md).
- **Palworld names, character images, and game data are not covered by that license** — see [`THIRD_PARTY_NOTICES.md`](./THIRD_PARTY_NOTICES.md) for exact boundaries.
- `oo2core_*_win64.dll` is explicitly ignored and never committed.

Unofficial, non-commercial community project with no affiliation with, authorization from, or endorsement by Pocketpair.
