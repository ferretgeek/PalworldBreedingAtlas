from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from pal_breed_helper import save_parser  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="对真实 Palworld 存档执行只读回归。")
    parser.add_argument("--save", required=True, help="Level.sav 的绝对路径")
    parser.add_argument(
        "--allow-unknown",
        action="store_true",
        help="允许出现权威数据中不存在的 CharacterID",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="输出机器可读 JSON 摘要",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    save = save_parser.resolved_path(os.path.expandvars(args.save), strict=False)
    if not save.is_file():
        print(f"失败：找不到存档 {save}", file=sys.stderr)
        return 2

    result = save_parser.analyze_save(save, lambda message: print(message))
    summary = {
        "source": result["source"],
        "savePath": result["savePath"],
        "ownedSpecies": len(result["ownedKeys"]),
        "ownedCount": sum(item["count"] for item in result["owned"]),
        "individualCount": sum(
            len(item.get("individuals", [])) for item in result["owned"]
        ),
        "maleCount": sum(int(item.get("male", 0)) for item in result["owned"]),
        "femaleCount": sum(int(item.get("female", 0)) for item in result["owned"]),
        "unknownGenderCount": sum(
            int(item.get("unknownGender", 0)) for item in result["owned"]
        ),
        "knownGenderCount": sum(
            int(item.get("male", 0)) + int(item.get("female", 0))
            for item in result["owned"]
        ),
        "excludedSpecies": len(result.get("excluded", [])),
        "excludedCount": sum(
            int(item.get("count", 0)) for item in result.get("excluded", [])
        ),
        "unknownSpecies": len(result.get("unknownData", [])),
        "unknownCount": sum(
            int(item.get("count", 0)) for item in result.get("unknownData", [])
        ),
        "crossWorldGeneSpecies": len(result.get("crossWorldGenes", [])),
        "crossWorldGeneCount": sum(
            int(item.get("count", 0))
            for item in result.get("crossWorldGenes", [])
        ),
        "crossWorldGeneExcludedSpecies": len(
            result.get("crossWorldGeneExcluded", [])
        ),
        "crossWorldGeneUnknownSpecies": len(
            result.get("crossWorldGeneUnknownData", [])
        ),
        "crossWorldGeneUnknownCount": sum(
            int(item.get("count", 0))
            for item in result.get("crossWorldGeneUnknownData", [])
        ),
        "globalStorageStatus": result.get("globalStorageStatus", "missing"),
        "globalStorageError": result.get("globalStorageError", ""),
        "dataInfo": result.get("dataInfo", {}),
    }

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(
            "回归摘要："
            f"正式帕鲁 {summary['ownedSpecies']} 种 / {summary['ownedCount']} 只；"
            f"个体资料 {summary['individualCount']} 条"
            f"（雄 {summary['maleCount']} / 雌 {summary['femaleCount']} / "
            f"未注明 {summary['unknownGenderCount']}）；"
            f"个体明细 {summary['individualCount']} 条 / 性别已识别 {summary['knownGenderCount']} 条；"
            f"已知排除 {summary['excludedSpecies']} 种 / {summary['excludedCount']} 只；"
            f"未知 {summary['unknownSpecies']} 种 / {summary['unknownCount']} 只；"
            f"跨界基因 {summary['globalStorageStatus']}"
            f"（{summary['crossWorldGeneSpecies']} 种 / "
            f"{summary['crossWorldGeneCount']} 条，默认不计入本世界）。"
        )

    if (
        summary["unknownSpecies"] or summary["crossWorldGeneUnknownSpecies"]
    ) and not args.allow_unknown:
        print("失败：仍有未知 CharacterID，请先更新或修复数据映射。", file=sys.stderr)
        unknown_items = result["unknownData"] + result.get(
            "crossWorldGeneUnknownData", []
        )
        for item in unknown_items:
            print(
                f"- {item['code']}: {item['count']}（{item.get('reason', '')}）",
                file=sys.stderr,
            )
        return 1
    if summary["globalStorageStatus"] == "error":
        print(
            "失败：当前世界可读，但跨界基因读取失败："
            f"{summary['globalStorageError']}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
