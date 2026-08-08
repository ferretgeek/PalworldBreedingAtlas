from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from update_game_data import (
    EXPECTED_BREEDING_SHA256,
    EXPECTED_BUILD_ID,
    EXPECTED_DB_SHA256,
    EXPECTED_MAX_BASE_WORK,
    OFFICIAL_PAL_COUNT,
    OFFICIAL_GAME_VERSION,
    OFFICIAL_RELEASE_GID,
    OFFICIAL_RELEASE_URL,
    PALCALC_COMMIT,
    PALCALC_COMMIT_DATE,
    REQUIRED_NEW_PALS,
    TERRARIA_INTERNALS,
    VALID_GENDERS,
    WORK_SUITABILITY_CAP,
)


class DataValidationError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataValidationError(f"无法读取 JSON {path}：{exc}") from exc


def read_window_assignment(path: Path, variable: str) -> Any:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise DataValidationError(f"无法读取 {path}：{exc}") from exc
    marker = f"window.{variable} = "
    position = text.find(marker)
    if position < 0:
        raise DataValidationError(f"{path.name} 缺少 {marker.strip()}")
    try:
        value, _ = json.JSONDecoder().raw_decode(text[position + len(marker) :])
    except json.JSONDecodeError as exc:
        raise DataValidationError(f"{path.name} 中 {variable} 不是有效 JSON：{exc}") from exc
    return value


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def is_local_absolute_path(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    return Path(value).is_absolute() or bool(
        re.match(r"^(?:[A-Za-z]:[\\/]|\\\\|//)", value)
    )


def validate_project(project_root: Path) -> dict[str, Any]:
    root = project_root.expanduser().resolve(strict=True)
    asset_root = root / "src" / "pal_breed_helper" / "assets"
    data_dir = asset_root / "data"
    breeding_path = data_dir / "breeding.js"
    paldeck_path = data_dir / "paldeck.js"
    game_data_path = data_dir / "game_data.json"
    provenance_path = data_dir / "provenance.json"
    internal_path = root / "src" / "pal_breed_helper" / "data" / "internal_names.json"

    pd = read_window_assignment(breeding_path, "PD")
    paldeck = read_window_assignment(paldeck_path, "PALDECK")
    work_icons = read_window_assignment(paldeck_path, "WORKICONS")
    game_data = read_json(game_data_path)
    provenance = read_json(provenance_path)
    internal = read_json(internal_path)

    errors: list[str] = []
    pals = pd.get("pals") if isinstance(pd, dict) else None
    breed = pd.get("breed") if isinstance(pd, dict) else None
    meta = pd.get("meta") if isinstance(pd, dict) else None
    require(isinstance(pals, dict), "PD.pals 必须是对象", errors)
    require(isinstance(breed, dict), "PD.breed 必须是对象", errors)
    require(isinstance(meta, dict), "PD.meta 必须是对象", errors)
    if not isinstance(pals, dict) or not isinstance(breed, dict) or not isinstance(meta, dict):
        raise DataValidationError("；".join(errors))

    ids = set(pals)
    require(len(pals) == OFFICIAL_PAL_COUNT, f"PD.pals 必须为 {OFFICIAL_PAL_COUNT}", errors)
    require(set(paldeck) == ids, "PALDECK 与 PD.pals ID 集合不一致", errors)
    require(set(breed) == ids, "PD.breed 与 PD.pals ID 集合不一致", errors)
    require("204" not in ids, "#204 WorldTreeDragon 不得进入默认数据", errors)
    require("12B" not in ids, "PlantSlime_Flower/12B 不得进入默认数据", errors)
    require(
        {str(index) for index in range(1, 204)} <= ids,
        "基础编号 1..203 必须完整",
        errors,
    )

    max_work = 0
    official_internals: set[str] = set()
    placeholder_names = {"en_text", "en Text", "zh_Hans_Text", "zh-Hans Text"}
    for key, pal in pals.items():
        require(isinstance(pal, dict), f"{key} 帕鲁记录必须是对象", errors)
        if not isinstance(pal, dict):
            continue
        for field in (
            "zh",
            "en",
            "internal",
            "r",
            "t",
            "work",
            "food",
            "stats",
            "genderProbability",
        ):
            require(field in pal, f"{key} 缺少字段 {field}", errors)
        official_internals.add(str(pal.get("internal")))
        require(pal.get("zh") not in placeholder_names, f"{key} 简中名仍是占位", errors)
        require(pal.get("en") not in placeholder_names, f"{key} 英文名仍是占位", errors)
        require(isinstance(pal.get("stats"), dict), f"{key}.stats 必须是对象", errors)
        gender = pal.get("genderProbability")
        require(isinstance(gender, dict), f"{key}.genderProbability 必须是对象", errors)
        if isinstance(gender, dict):
            try:
                total = float(gender.get("male")) + float(gender.get("female"))
                require(abs(total - 1.0) < 1e-9, f"{key} 性别概率之和不为 1", errors)
            except (TypeError, ValueError):
                errors.append(f"{key} 性别概率不是数字")
        work = pal.get("work")
        require(isinstance(work, list), f"{key}.work 必须是数组", errors)
        if isinstance(work, list):
            for item in work:
                try:
                    level = int(item["lv"])
                except (KeyError, TypeError, ValueError):
                    errors.append(f"{key} 工作适性行无有效等级")
                    continue
                require(1 <= level <= WORK_SUITABILITY_CAP, f"{key} 工作等级越界：{level}", errors)
                max_work = max(max_work, level)
        deck = paldeck.get(key)
        require(isinstance(deck, dict), f"PALDECK.{key} 缺失", errors)
        if isinstance(deck, dict):
            require(deck.get("internal") == pal.get("internal"), f"{key} internal 不一致", errors)
            require(deck.get("work") == pal.get("work"), f"{key} work 不一致", errors)
            require(deck.get("types") == pal.get("t"), f"{key} types 不一致", errors)
            image = deck.get("img")
            require(isinstance(image, str) and bool(image), f"{key} 缺少图标路径", errors)
            if isinstance(image, str) and image:
                require((asset_root / image).is_file(), f"{key} 图标不存在：{image}", errors)

    require(max_work == EXPECTED_MAX_BASE_WORK, f"基础工作最大值必须为 {EXPECTED_MAX_BASE_WORK}", errors)
    require(meta.get("gameVersion") == OFFICIAL_GAME_VERSION, "PD.meta 游戏版本不是 1.0.0", errors)
    require(meta.get("buildId") == EXPECTED_BUILD_ID, "PD.meta Steam buildid 不是已验证的 1.0 构建", errors)
    generated_at = meta.get("generatedAtUtc")
    require(
        isinstance(generated_at, str) and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}T.+Z", generated_at)),
        "PD.meta.generatedAtUtc 必须是 UTC 时间戳",
        errors,
    )
    require(meta.get("updatedAt") == generated_at, "PD.meta.updatedAt 必须与 generatedAtUtc 一致", errors)
    require(meta.get("workSuitabilityCap") == WORK_SUITABILITY_CAP, "工作适性系统上限必须记录为 10", errors)
    require(meta.get("maxBaseWorkSuitability") == EXPECTED_MAX_BASE_WORK, "meta 基础工作最大值错误", errors)

    element_status = (meta.get("fieldStatus") or {}).get("elements")
    empty_elements = [key for key, pal in pals.items() if not pal.get("t")]
    if empty_elements:
        require(
            element_status == "unknown",
            "存在空元素时必须在 meta.fieldStatus.elements 显式标为 unknown",
            errors,
        )

    for key, (expected_internal, expected_en, expected_zh) in REQUIRED_NEW_PALS.items():
        pal = pals.get(key) or {}
        require(pal.get("internal") == expected_internal, f"缺少新帕鲁 {key}/{expected_internal}", errors)
        require(pal.get("en") == expected_en, f"{key} 英文名错误", errors)
        require(pal.get("zh") == expected_zh, f"{key} 简中名错误", errors)
    require((pals.get("38") or {}).get("zh") == "吊缚灵", "#38 必须为吊缚灵", errors)
    require((pals.get("38B") or {}).get("zh") == "冰缚灵", "#38B 必须为冰缚灵", errors)

    total_breeding = 0
    for child, pairs in breed.items():
        require(isinstance(pairs, list) and bool(pairs), f"{child} 配种列表为空", errors)
        if not isinstance(pairs, list):
            continue
        total_breeding += len(pairs)
        seen: set[tuple[str, str, str, str]] = set()
        for pair in pairs:
            require(isinstance(pair, list) and len(pair) >= 3, f"{child} 配种行格式错误", errors)
            if not isinstance(pair, list) or len(pair) < 3:
                continue
            parent1, parent2, constraint = pair[:3]
            require(parent1 in ids and parent2 in ids, f"{child} 引用未知父母 {parent1}/{parent2}", errors)
            require(isinstance(constraint, dict), f"{child} 性别约束必须是对象", errors)
            if not isinstance(constraint, dict):
                continue
            gender1 = constraint.get("parent1Gender")
            gender2 = constraint.get("parent2Gender")
            require(gender1 in VALID_GENDERS and gender2 in VALID_GENDERS, f"{child} 性别约束非法", errors)
            identity = (str(parent1), str(parent2), str(gender1), str(gender2))
            require(identity not in seen, f"{child} 存在重复配种行 {identity}", errors)
            seen.add(identity)

    expected_203 = [
        [
            "203",
            "203",
            {"parent1Gender": "WILDCARD", "parent2Gender": "WILDCARD"},
        ]
    ]
    require(breed.get("203") == expected_203, "#203 作为子代时必须仅有 203×203", errors)

    require(isinstance(internal, dict) and internal.get("schemaVersion") == 2, "internal_names schemaVersion 必须为 2", errors)
    mapping = internal.get("mapping") if isinstance(internal, dict) else None
    excluded = internal.get("excluded") if isinstance(internal, dict) else None
    require(isinstance(mapping, dict), "internal_names.mapping 必须是对象", errors)
    require(isinstance(excluded, dict), "internal_names.excluded 必须是对象", errors)
    if isinstance(mapping, dict):
        require(set(mapping) == official_internals, "internal_names.mapping 与正式帕鲁不一致", errors)
        expected_mapping = {
            str(pal.get("internal")): key
            for key, pal in pals.items()
            if isinstance(pal, dict)
        }
        require(
            mapping == expected_mapping,
            "internal_names.mapping 必须直接映射到稳定图鉴 key，不能经英文名二次关联",
            errors,
        )
        for key, (expected_internal, _, _) in REQUIRED_NEW_PALS.items():
            require(
                mapping.get(expected_internal) == key,
                f"新帕鲁 {expected_internal} 必须直接映射到 {key}",
                errors,
            )
    if isinstance(excluded, dict):
        require(
            TERRARIA_INTERNALS <= set(excluded),
            "internal_names.excluded 缺少 Terraria 特殊单位",
            errors,
        )
        for value in TERRARIA_INTERNALS:
            require((excluded.get(value) or {}).get("category") == "special/terraria", f"{value} 分类错误", errors)
        for value in ("BlackFurDragon", "DarkMutant"):
            record = excluded.get(value)
            if record is not None:
                require(record.get("category") == "unreleased/unknown", f"{value} 必须标为未发布", errors)
                require(record.get("trustedLocalization") is False, f"{value} 不得信任占位本地化", errors)

    require(game_data.get("meta") == meta, "game_data.meta 与 PD.meta 不一致", errors)
    require(game_data.get("pals") == pals, "game_data.pals 与 PD.pals 不一致", errors)
    require(game_data.get("breed") == breed, "game_data.breed 与 PD.breed 不一致", errors)
    require(provenance.get("source", {}).get("commit") == PALCALC_COMMIT, "provenance PalCalc commit 错误", errors)
    require(
        provenance.get("source", {}).get("commitDate") == PALCALC_COMMIT_DATE,
        "provenance PalCalc commit 时间错误",
        errors,
    )
    require(provenance.get("source", {}).get("db", {}).get("pinnedMatch") is True, "provenance db 未通过固定哈希", errors)
    require(provenance.get("source", {}).get("breeding", {}).get("pinnedMatch") is True, "provenance breeding 未通过固定哈希", errors)
    require(provenance.get("source", {}).get("db", {}).get("sha256") == EXPECTED_DB_SHA256, "provenance db SHA256 错误", errors)
    require(
        provenance.get("source", {}).get("breeding", {}).get("sha256")
        == EXPECTED_BREEDING_SHA256,
        "provenance breeding SHA256 错误",
        errors,
    )
    require(provenance.get("counts", {}).get("officialPals") == OFFICIAL_PAL_COUNT, "provenance 287 断言错误", errors)
    counts = provenance.get("counts", {})
    require(counts.get("sourcePals") == 299, "provenance 源帕鲁数量必须为 299", errors)
    require(counts.get("basePals") == 203, "provenance 基础帕鲁数量必须为 203", errors)
    require(counts.get("variantPals") == 84, "provenance 亚种数量必须为 84", errors)
    require(counts.get("excludedSourceRows") == 12, "provenance 排除源行必须为 12", errors)
    require(counts.get("sourceBreedingRows") == 44851, "provenance 源配种行必须为 44851", errors)
    require(counts.get("outputBreedingRows") == total_breeding, "provenance 输出配种行错误", errors)
    require(
        counts.get("skippedBreedingRows")
        == counts.get("sourceBreedingRows", 0) - total_breeding,
        "provenance 跳过配种行错误",
        errors,
    )
    require(counts.get("maxBaseWorkSuitability") == max_work, "provenance 基础工作最大值错误", errors)
    require(counts.get("workSuitabilityCap") == WORK_SUITABILITY_CAP, "provenance 工作系统上限错误", errors)
    require(
        provenance.get("generatedAtUtc") == generated_at,
        "provenance.generatedAtUtc 与 PD.meta.generatedAtUtc 不一致",
        errors,
    )
    require(provenance.get("game", {}).get("found") is True, "provenance 缺少本机 Steam 构建证据", errors)
    require(provenance.get("game", {}).get("buildId") == EXPECTED_BUILD_ID, "provenance Steam buildid 不是已验证的 1.0 构建", errors)
    require(
        not is_local_absolute_path(provenance.get("game", {}).get("manifestPath")),
        "provenance 不得记录本机 Steam manifest 绝对路径",
        errors,
    )
    require(
        not is_local_absolute_path(provenance.get("icons", {}).get("assetManifestPath")),
        "provenance 不得记录本机资源 manifest 绝对路径",
        errors,
    )
    release = provenance.get("officialRelease", {})
    require(release.get("version") == OFFICIAL_GAME_VERSION, "provenance 官方版本错误", errors)
    require(release.get("gid") == OFFICIAL_RELEASE_GID, "provenance 官方公告 GID 错误", errors)
    require(release.get("url") == OFFICIAL_RELEASE_URL, "provenance 官方公告 URL 错误", errors)
    require(provenance.get("validation", {}).get("oldSnapshotFieldsReused") is False, "不得复用旧快照字段", errors)
    require(
        provenance.get("validation", {}).get("lamballJellroySentinel")
        == "passed-woolipop-2820-not-ribbuny-2860",
        "棉悠悠 × 海月灵争议配方门禁未通过",
        errors,
    )

    filters = provenance.get("filters")
    require(isinstance(filters, list), "provenance.filters 必须是数组", errors)
    if isinstance(filters, list):
        filter_by_name = {
            str(item.get("name")): item for item in filters if isinstance(item, dict)
        }
        require(
            set(filter_by_name)
            == {"unindexed-pals", "gumoss-special", "world-tree-hidden-boss"},
            "provenance.filters 集合不完整",
            errors,
        )
        require(
            (filter_by_name.get("unindexed-pals") or {}).get("excludedSourceRows")
            == 11,
            "未编号单位排除数量错误",
            errors,
        )
        require(
            (filter_by_name.get("gumoss-special") or {}).get("excludedSourceRows")
            == 1,
            "特殊米露菲排除数量错误",
            errors,
        )
        require(
            (filter_by_name.get("world-tree-hidden-boss") or {}).get(
                "excludedSourceRows"
            )
            == 0,
            "#204 源行数量错误",
            errors,
        )

    require(
        provenance.get("fieldStatus") == meta.get("fieldStatus"),
        "provenance.fieldStatus 与 meta 不一致",
        errors,
    )
    elements = provenance.get("elements", {})
    if element_status == "unknown":
        require(elements.get("status") == "unknown", "元素未知状态未同步到 provenance", errors)
        require(elements.get("knownPalCount") == 0, "未知元素状态不得含已知帕鲁", errors)
    else:
        require(
            elements.get("status") in {"current-pak-export", "pinned-build-snapshot"},
            "元素来源不是当前 PAK 导出或固定 Build 快照",
            errors,
        )
        require(
            elements.get("knownPalCount") == OFFICIAL_PAL_COUNT,
            "元素导出未覆盖 287 只",
            errors,
        )
        require(elements.get("buildId") == EXPECTED_BUILD_ID, "元素导出 buildId 错误", errors)
        if elements.get("status") == "pinned-build-snapshot":
            require(bool(elements.get("sourceUrl")), "属性快照缺少来源 URL", errors)
            require(
                bool(re.fullmatch(r"[0-9a-f]{64}", str(elements.get("sourcePageSha256") or ""))),
                "属性快照缺少页面 SHA256",
                errors,
            )

    icons = provenance.get("icons", {})
    placeholder_count = icons.get("placeholderCount")
    missing_icons = icons.get("missing")
    require(isinstance(placeholder_count, int), "provenance 图标占位数量缺失", errors)
    require(isinstance(missing_icons, list), "provenance 缺图清单必须是数组", errors)
    if isinstance(placeholder_count, int) and isinstance(missing_icons, list):
        require(len(missing_icons) == placeholder_count, "图标占位数量与清单不一致", errors)
        require(
            icons.get("retainedExistingCount", 0)
            + icons.get("extractedFromPakAssetsCount", 0)
            + placeholder_count
            == OFFICIAL_PAL_COUNT,
            "图标来源计数之和必须为 287",
            errors,
        )

    expected_output_keys = {
        "src/pal_breed_helper/assets/data/breeding.js",
        "src/pal_breed_helper/assets/data/paldeck.js",
        "src/pal_breed_helper/assets/data/game_data.json",
        "src/pal_breed_helper/data/internal_names.json",
    }
    outputs = provenance.get("outputs")
    require(isinstance(outputs, dict), "provenance.outputs 必须是对象", errors)
    if isinstance(outputs, dict):
        require(set(outputs) == expected_output_keys, "provenance.outputs 键集合不完整", errors)
    for relative, expected_hash in (outputs or {}).items():
        output_path = root / relative
        require(output_path.is_file(), f"provenance 输出不存在：{relative}", errors)
        if output_path.is_file():
            require(sha256_file(output_path) == expected_hash, f"输出 SHA256 不匹配：{relative}", errors)

    require(bool(work_icons), "WORKICONS 不得为空", errors)
    if errors:
        raise DataValidationError("\n- " + "\n- ".join(errors))
    return {
        "officialPals": len(pals),
        "breedingRows": total_breeding,
        "maxBaseWorkSuitability": max_work,
        "workSuitabilityCap": meta.get("workSuitabilityCap"),
        "elementStatus": element_status,
        "placeholderIcons": provenance.get("icons", {}).get("placeholderCount"),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="校验帕鲁配种助手 1.0 数据契约。")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="项目根目录",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        summary = validate_project(args.project_root)
        print(
            "数据校验通过："
            f"{summary['officialPals']} 只正式帕鲁，"
            f"{summary['breedingRows']} 条配种记录，"
            f"基础工作最大 {summary['maxBaseWorkSuitability']}，"
            f"系统上限 {summary['workSuitabilityCap']}，"
            f"元素状态 {summary['elementStatus']}，"
            f"占位图标 {summary['placeholderIcons']}。"
        )
        return 0
    except (DataValidationError, OSError) as exc:
        print(f"数据校验失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
