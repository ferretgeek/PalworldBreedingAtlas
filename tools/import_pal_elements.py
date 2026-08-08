from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.request
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path


SOURCE_URL = "https://www.palmods.gg/tools/palpedia/lamball"
GAME_VERSION = "1.0.0"
BUILD_ID = "24088745"
OFFICIAL_PAL_COUNT = 287
ELEMENT_NAMES = {
    "neutral": "Normal",
    "fire": "Fire",
    "water": "Water",
    "grass": "Leaf",
    "electric": "Electricity",
    "ice": "Ice",
    "ground": "Earth",
    "dark": "Dark",
    "dragon": "Dragon",
}
ROW_PATTERN = re.compile(
    r'\\"slug\\":\\"(?P<slug>[^\\]+)\\",'
    r'\\"name\\":\\"(?P<name>[^\\]+)\\",'
    r'\\"paldeckLabel\\":\\"#(?P<label>[^\\]+)\\"'
    r'.*?\\"elements\\":\[(?P<elements>.*?)\]'
    r'.*?\\"paldeckNumber\\":(?P<number>\d+)',
    re.DOTALL,
)


def fetch_page(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "PalBreedHelperDataImporter/1.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def extract_rows(page: bytes) -> dict[str, dict[str, object]]:
    text = page.decode("utf-8")
    rows: dict[str, dict[str, object]] = {}
    for match in ROW_PATTERN.finditer(text):
        raw_elements = re.findall(r'\\"([^\\]+)\\"', match.group("elements"))
        rows[match.group("label")] = {
            "name": match.group("name").strip(),
            "elements": [ELEMENT_NAMES[value] for value in raw_elements],
        }
    if len(rows) != OFFICIAL_PAL_COUNT:
        raise ValueError(f"属性快照必须为 {OFFICIAL_PAL_COUNT} 条，实际 {len(rows)}")
    return rows


def build_snapshot(project_root: Path, page: bytes, source_url: str = SOURCE_URL) -> dict[str, object]:
    data_path = (
        project_root
        / "src"
        / "pal_breed_helper"
        / "assets"
        / "data"
        / "game_data.json"
    )
    game_data = json.loads(data_path.read_text(encoding="utf-8"))
    pals = game_data["pals"]
    rows = extract_rows(page)
    if set(rows) != set(pals):
        missing = sorted(set(pals) - set(rows))
        extra = sorted(set(rows) - set(pals))
        raise ValueError(f"属性快照与正式图鉴不一致：缺少 {missing[:5]}，多出 {extra[:5]}")

    output_pals: OrderedDict[str, list[str]] = OrderedDict()
    for key, pal in pals.items():
        row = rows[key]
        source_name = str(row["name"]).strip()
        expected_name = str(pal["en"]).strip()
        # PalMods 对两个条目带展示后缀/尾空格；编号与 287 集合仍严格一致。
        if source_name not in {expected_name, "Gumoss (Special)"}:
            raise ValueError(f"#{key} 英文名不一致：{expected_name!r} / {source_name!r}")
        output_pals[str(pal["internal"])] = list(row["elements"])

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return OrderedDict(
        (
            (
                "meta",
                OrderedDict(
                    (
                        ("status", "pinned-build-snapshot"),
                        ("gameVersion", GAME_VERSION),
                        ("buildId", BUILD_ID),
                        ("officialPalCount", OFFICIAL_PAL_COUNT),
                        ("sourceName", "PalMods.gg Palpedia 1.0 game-data snapshot"),
                        ("sourceUrl", source_url),
                        ("sourcePageSha256", hashlib.sha256(page).hexdigest()),
                        ("snapshotAtUtc", now),
                        (
                            "trustNote",
                            "版本化第三方游戏文件快照，仅补充 PalCalc 未导出的属性字段；按 Build 24088745 的 287 条图鉴逐编号核对并固定页面哈希。",
                        ),
                    )
                ),
            ),
            ("pals", output_pals),
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="抓取并标准化 Palworld 1.0 的 287 条属性快照。")
    parser.add_argument("--source-url", default=SOURCE_URL)
    parser.add_argument("--output-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    project_root = args.output_root.expanduser().resolve(strict=True)
    page = fetch_page(args.source_url)
    snapshot = build_snapshot(project_root, page, args.source_url)
    output = project_root / "tools" / "data_sources" / "pal_elements.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"属性快照已写入：{output.name}，{len(snapshot['pals'])} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
