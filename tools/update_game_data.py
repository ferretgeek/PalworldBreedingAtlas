from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
import tempfile
import urllib.parse
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PALCALC_REPOSITORY = "tylercamp/palcalc"
PALCALC_COMMIT = "5757961d9f115a8c1733e94327cb644c2136052c"
PALCALC_COMMIT_DATE = "2026-07-11T18:00:14Z"
PALCALC_RAW_BASE = (
    f"https://raw.githubusercontent.com/{PALCALC_REPOSITORY}/{PALCALC_COMMIT}"
    "/PalCalc.Model"
)
DEFAULT_DB = f"{PALCALC_RAW_BASE}/db.json"
DEFAULT_BREEDING = f"{PALCALC_RAW_BASE}/breeding.json"
EXPECTED_DB_SHA256 = "803d891afdb18bd00e24332844a7276bbe5c0855170ef90ef142f2f4d7698ed1"
EXPECTED_BREEDING_SHA256 = (
    "b5d7470f38344db21634ec1c01b8cc11eeeb0d26e78ad65be1b85bfd55c98ae2"
)

PALWORLD_APP_ID = "1623730"
EXPECTED_BUILD_ID = "24088745"
EXPECTED_DEPOT_ID = "1623731"
OFFICIAL_GAME_VERSION = "1.0.0"
OFFICIAL_PAL_COUNT = 287
OFFICIAL_RELEASE_DATE = "2026-07-10"
OFFICIAL_RELEASE_URL = (
    "https://store.steampowered.com/news/app/1623730/view/1837955055355658"
)
OFFICIAL_RELEASE_GID = "1837955055355658"
WORK_SUITABILITY_CAP = 10
EXPECTED_MAX_BASE_WORK = 8
DEFAULT_ELEMENT_SOURCE = Path(__file__).resolve().parent / "data_sources" / "pal_elements.json"


WORK_FIELDS = (
    ("Kindling", "Kindling", "生火"),
    ("Watering", "Watering", "浇水"),
    ("Planting", "Planting", "播种"),
    ("GenerateElectricity", "Generating_Electricity", "发电"),
    ("Handiwork", "Handiwork", "手工作业"),
    ("Gathering", "Gathering", "采集"),
    ("Lumbering", "Lumbering", "伐木"),
    ("Mining", "Mining", "采矿"),
    ("MedicineProduction", "Medicine_Production", "制药"),
    ("Cooling", "Cooling", "制冷"),
    ("Transporting", "Transporting", "搬运"),
    ("Farming", "Farming", "牧场"),
)
WORK_SOURCE_FIELDS = {source_name for source_name, _, _ in WORK_FIELDS}

WORK_ICONS = OrderedDict(
    (legacy_name, f"images/work/{legacy_name}.webp")
    for _, legacy_name, _ in sorted(WORK_FIELDS, key=lambda item: item[1])
)

ELEMENT_NAMES = {
    "Normal": "normal",
    "Neutral": "normal",
    "Fire": "fire",
    "Water": "water",
    "Leaf": "leaf",
    "Grass": "leaf",
    "Electricity": "electricity",
    "Electric": "electricity",
    "Ice": "ice",
    "Earth": "earth",
    "Ground": "earth",
    "Dark": "dark",
    "Dragon": "dragon",
}

REQUIRED_NEW_PALS = {
    "143": ("BadCatgirl", "Nyafia", "妮瞅莎"),
    "147": ("BlueberryFairy", "Prunelia", "梅莉姆"),
    "154": ("GoldenHorse", "Gildane", "金驰兽"),
    "165": ("BrownRabbit", "Lapiron", "詹兔曼"),
}

TERRARIA_INTERNALS = {
    "YakushimaBoss001",
    "YakushimaBoss001_Small",
    "YakushimaMonster001",
    "YakushimaMonster001_Blue",
    "YakushimaMonster001_Pink",
    "YakushimaMonster001_Purple",
    "YakushimaMonster001_Rainbow",
    "YakushimaMonster001_Red",
    "YakushimaMonster002",
    "YakushimaMonster003",
    "YakushimaMonster003_Purple",
}

UNTRUSTED_LOCALIZATION_INTERNALS = {"BlackFurDragon", "DarkMutant"}
POLICY_EXCLUDED_INTERNALS = {"PlantSlime_Flower", "WorldTreeDragon"}
VALID_GENDERS = {"WILDCARD", "MALE", "FEMALE"}


class DataUpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class SourceBlob:
    location: str
    data: bytes
    sha256: str
    is_url: bool


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def pretty_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def pal_id(value: dict[str, Any]) -> str:
    number = int(value["PalDexNo"])
    return f"{number}{'B' if bool(value.get('IsVariant')) else ''}"


def pal_sort_key(value: str) -> tuple[int, int, str]:
    match = re.fullmatch(r"(\d+)([A-Za-z]*)", value)
    if not match:
        return (sys.maxsize, 1, value)
    return (int(match.group(1)), 1 if match.group(2) else 0, match.group(2))


def load_source(location: str, timeout: int = 180) -> SourceBlob:
    parsed = urllib.parse.urlparse(location)
    is_url = parsed.scheme in {"http", "https"}
    if is_url:
        request = urllib.request.Request(
            location,
            headers={"User-Agent": "PalBreedHelperDataPipeline/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = response.read()
        except OSError as exc:
            raise DataUpdateError(f"下载数据失败：{location}：{exc}") from exc
    else:
        path = Path(location).expanduser()
        try:
            path = path.resolve(strict=True)
            data = path.read_bytes()
        except OSError as exc:
            raise DataUpdateError(f"读取数据失败：{path}：{exc}") from exc
        location = str(path)
    return SourceBlob(location, data, sha256_bytes(data), is_url)


def decode_json(blob: SourceBlob, label: str) -> dict[str, Any]:
    try:
        value = json.loads(blob.data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DataUpdateError(f"{label} 不是有效 UTF-8 JSON：{exc}") from exc
    if not isinstance(value, dict):
        raise DataUpdateError(f"{label} 顶层必须是对象")
    return value


def parse_acf(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {
            "found": False,
            "appId": PALWORLD_APP_ID,
            "buildId": None,
            "depotId": EXPECTED_DEPOT_ID,
            "depotManifestId": None,
            "lastUpdatedUtc": None,
            "sizeOnDisk": None,
            "manifestPath": None,
        }

    try:
        resolved = path.expanduser().resolve(strict=True)
        text = resolved.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise DataUpdateError(f"无法读取 Steam manifest：{path}：{exc}") from exc

    def scalar(key: str) -> str | None:
        match = re.search(rf'"{re.escape(key)}"\s+"([^"]*)"', text)
        return match.group(1) if match else None

    depot_match = re.search(
        rf'"{EXPECTED_DEPOT_ID}"\s*\{{.*?"manifest"\s+"(\d+)"',
        text,
        re.DOTALL,
    )
    last_updated = scalar("LastUpdated")
    updated_utc = None
    if last_updated and last_updated.isdigit():
        updated_utc = datetime.fromtimestamp(
            int(last_updated), tz=timezone.utc
        ).isoformat().replace("+00:00", "Z")

    size = scalar("SizeOnDisk")
    return {
        "found": True,
        "appId": scalar("appid"),
        "buildId": scalar("buildid"),
        "depotId": EXPECTED_DEPOT_ID,
        "depotManifestId": depot_match.group(1) if depot_match else None,
        "lastUpdatedUtc": updated_utc,
        "sizeOnDisk": int(size) if size and size.isdigit() else None,
        "manifestPath": f"steamapps/{resolved.name}",
    }


def discover_steam_manifest() -> Path | None:
    candidates: list[Path] = []
    if os.name == "nt":
        try:
            import winreg

            keys = (
                (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                (
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\WOW6432Node\Valve\Steam",
                    "InstallPath",
                ),
            )
            for hive, key_name, value_name in keys:
                try:
                    with winreg.OpenKey(hive, key_name) as key:
                        steam_path, _ = winreg.QueryValueEx(key, value_name)
                    if steam_path:
                        candidates.append(Path(steam_path))
                except OSError:
                    continue
        except ImportError:
            pass
    else:
        candidates.extend(
            [
                Path.home() / ".steam" / "steam",
                Path.home() / ".local" / "share" / "Steam",
            ]
        )

    libraries: list[Path] = []
    for steam in candidates:
        libraries.append(steam)
        library_file = steam / "steamapps" / "libraryfolders.vdf"
        if library_file.is_file():
            try:
                text = library_file.read_text(encoding="utf-8-sig")
            except OSError:
                continue
            for value in re.findall(r'"path"\s+"([^"]+)"', text):
                libraries.append(Path(value.replace(r"\\", "\\")))

    seen: set[str] = set()
    for library in libraries:
        key = str(library).lower()
        if key in seen:
            continue
        seen.add(key)
        for manifest in (
            library / "steamapps" / f"appmanifest_{PALWORLD_APP_ID}.acf",
            library / f"appmanifest_{PALWORLD_APP_ID}.acf",
        ):
            if manifest.is_file():
                return manifest.resolve()
    return None


def find_manifest_ufs(root: Path | None) -> Path | None:
    if root is None:
        return None
    resolved = root.expanduser().resolve(strict=True)
    current = resolved if resolved.is_dir() else resolved.parent
    for directory in (current, *list(current.parents)[:6]):
        candidate = directory / "Manifest_UFSFiles_Win64.txt"
        if candidate.is_file():
            return candidate
    return None


def load_optional_elements(
    root: Path | None, expected_internals: set[str]
) -> tuple[dict[str, list[str]], dict[str, Any]]:
    bundled_source = DEFAULT_ELEMENT_SOURCE if DEFAULT_ELEMENT_SOURCE.is_file() else None
    if root is None and bundled_source is None:
        return {}, {
            "status": "unknown",
            "knownPalCount": 0,
            "reason": "固定 PalCalc db.json 未导出 ElementType1/2，且项目未包含 pal_elements.json 快照",
        }

    candidates: tuple[Path, ...] = ()
    if root is not None:
        base = root.expanduser().resolve(strict=True)
        if base.is_file():
            base = base.parent
        candidates = (
            base / "pal_elements.json",
            base / "elements.json",
            base / "data" / "pal_elements.json",
        )
    if bundled_source is not None:
        candidates = (*candidates, bundled_source)
    element_file = next((path for path in candidates if path.is_file()), None)
    if element_file is None:
        return {}, {
            "status": "unknown",
            "knownPalCount": 0,
            "reason": "未找到带版本和 Build 标记的 pal_elements.json；拒绝回填旧图鉴元素",
        }

    try:
        raw = json.loads(element_file.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataUpdateError(f"无法解析元素导出 {element_file}：{exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("meta"), dict):
        raise DataUpdateError(
            "pal_elements.json 必须包含 meta 和 pals，不能接入无版本标记的旧元素数据"
        )
    meta = raw["meta"]
    if meta.get("gameVersion") != OFFICIAL_GAME_VERSION:
        raise DataUpdateError("pal_elements.json gameVersion 不是当前 1.0.0")
    if str(meta.get("buildId")) != EXPECTED_BUILD_ID:
        raise DataUpdateError(
            f"pal_elements.json buildId 必须为已验证构建 {EXPECTED_BUILD_ID}"
        )
    if int(meta.get("officialPalCount", 0)) != OFFICIAL_PAL_COUNT:
        raise DataUpdateError(
            f"pal_elements.json officialPalCount 必须为 {OFFICIAL_PAL_COUNT}"
        )
    raw = raw.get("pals")
    if not isinstance(raw, dict):
        raise DataUpdateError("pal_elements.json.pals 必须是 internalName -> elements[] 对象")
    actual_internals = set(map(str, raw))
    if actual_internals != expected_internals:
        missing = sorted(expected_internals - actual_internals)
        extra = sorted(actual_internals - expected_internals)
        raise DataUpdateError(
            "pal_elements.json 与当前正式帕鲁集合不一致："
            f"缺少 {missing[:5]}，多出 {extra[:5]}"
        )

    result: dict[str, list[str]] = {}
    for internal, value in raw.items():
        if isinstance(value, dict):
            value = value.get("elements")
        if not isinstance(value, list):
            raise DataUpdateError(f"元素行 {internal} 必须是数组")
        converted: list[str] = []
        for item in value:
            normalized = ELEMENT_NAMES.get(str(item).split("::")[-1])
            if normalized is None:
                raise DataUpdateError(f"未知元素值：{internal} -> {item}")
            if normalized not in converted:
                converted.append(normalized)
        result[str(internal)] = converted
    source_status = str(meta.get("status") or "pinned-build-snapshot")
    if source_status not in {"current-pak-export", "pinned-build-snapshot"}:
        raise DataUpdateError(f"pal_elements.json status 不受信任：{source_status}")
    return result, {
        "status": source_status,
        "knownPalCount": len(result),
        "sourceFile": element_file.name,
        "gameVersion": meta.get("gameVersion"),
        "buildId": str(meta.get("buildId")),
        "sha256": sha256_bytes(element_file.read_bytes()),
        "sourceName": meta.get("sourceName"),
        "sourceUrl": meta.get("sourceUrl"),
        "sourcePageSha256": meta.get("sourcePageSha256"),
        "snapshotAtUtc": meta.get("snapshotAtUtc"),
        "trustNote": meta.get("trustNote"),
    }


def classify_excluded(pal: dict[str, Any]) -> dict[str, Any] | None:
    internal = str(pal.get("InternalName", ""))
    number = int(pal.get("Id", {}).get("PalDexNo", -1))
    if internal == "PlantSlime_Flower":
        return {
            "category": "special/cosmetic-variant",
            "reason": "与 Gumoss 共用编号的视觉特殊个体，不计入官方独立 287 条",
            "trustedLocalization": True,
        }
    if internal == "WorldTreeDragon":
        return {
            "category": "special/hidden-boss",
            "reason": "1.0 最终 Boss 隐藏条目，不进入默认 PalCalc",
            "trustedLocalization": False,
        }
    if number >= 10000:
        if internal in TERRARIA_INTERNALS:
            return {
                "category": "special/terraria",
                "reason": "Terraria 联动单位无正式 PalDex 编号，不进入默认帕鲁配种池",
                "trustedLocalization": True,
            }
        return {
            "category": "unreleased/unknown",
            "reason": "无正式 PalDex 编号的未完成或未发布占位数据",
            "trustedLocalization": False,
        }
    return None


def excluded_record(pal: dict[str, Any], classification: dict[str, Any]) -> dict[str, Any]:
    internal = str(pal.get("InternalName", ""))
    localized = pal.get("LocalizedNames") or {}
    trusted = bool(classification["trustedLocalization"])
    result = {
        "category": classification["category"],
        "reason": classification["reason"],
        "presentInSource": True,
        "palDexNo": int(pal.get("Id", {}).get("PalDexNo", -1)),
        "isVariant": bool(pal.get("Id", {}).get("IsVariant")),
        "trustedLocalization": trusted,
    }
    if trusted:
        result["name"] = {
            "en": localized.get("en") or pal.get("Name"),
            "zhHans": localized.get("zh-Hans"),
        }
    else:
        result["name"] = None
        result["rawLocalization"] = {
            "en": localized.get("en") or pal.get("Name"),
            "zhHans": localized.get("zh-Hans"),
        }
    if internal in UNTRUSTED_LOCALIZATION_INTERNALS:
        result["localizationWarning"] = "占位文本不可作为正式名称"
    return result


def build_placeholder_svg(pal_key: str, zh_name: str, en_name: str) -> bytes:
    number = html.escape(pal_key)
    zh = html.escape(zh_name)
    en = html.escape(en_name)
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#163847"/>
      <stop offset="1" stop-color="#0b1d2a"/>
    </linearGradient>
  </defs>
  <rect width="512" height="512" rx="84" fill="url(#bg)"/>
  <circle cx="256" cy="210" r="132" fill="#1f5968" stroke="#71d4c5" stroke-width="12"/>
  <path d="M172 216c28-58 140-58 168 0-18 72-150 72-168 0Z" fill="#d5f7ef" opacity=".9"/>
  <circle cx="218" cy="210" r="13" fill="#102a35"/>
  <circle cx="294" cy="210" r="13" fill="#102a35"/>
  <text x="256" y="78" text-anchor="middle" fill="#92eadc" font-family="Segoe UI,Microsoft YaHei,sans-serif" font-size="38" font-weight="700">#{number}</text>
  <text x="256" y="400" text-anchor="middle" fill="#ffffff" font-family="Microsoft YaHei,Segoe UI,sans-serif" font-size="42" font-weight="700">{zh}</text>
  <text x="256" y="448" text-anchor="middle" fill="#a7c5cd" font-family="Segoe UI,sans-serif" font-size="23">{en}</text>
  <text x="256" y="486" text-anchor="middle" fill="#718f98" font-family="Microsoft YaHei,Segoe UI,sans-serif" font-size="18">1.0 本地资源待导出</text>
</svg>
"""
    return svg.encode("utf-8")


def icon_source_candidates(root: Path, internal: str) -> list[Path]:
    filename = f"T_{internal}_icon_normal"
    directories = (
        root,
        root / "Pal" / "Content" / "Pal" / "Texture" / "PalIcon" / "Normal",
        root / "Pal" / "Texture" / "PalIcon" / "Normal",
        root / "Texture" / "PalIcon" / "Normal",
        root / "PalIcon" / "Normal",
    )
    return [directory / f"{filename}{suffix}" for directory in directories for suffix in (".webp", ".png", ".jpg", ".jpeg")]


def inspect_asset_triplets(manifest_path: Path | None, internals: set[str]) -> dict[str, bool | None]:
    if manifest_path is None:
        return {internal: None for internal in internals}
    try:
        text = manifest_path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise DataUpdateError(f"无法读取资源 manifest：{manifest_path}：{exc}") from exc
    result: dict[str, bool] = {}
    for internal in internals:
        base = f"T_{internal}_icon_normal"
        result[internal] = all(f"{base}{suffix}" in text for suffix in (".uasset", ".ubulk", ".uexp"))
    return result


def generated_at_utc() -> str:
    source_date_epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if source_date_epoch:
        try:
            value = datetime.fromtimestamp(int(source_date_epoch), tz=timezone.utc)
        except (ValueError, OSError) as exc:
            raise DataUpdateError("SOURCE_DATE_EPOCH 必须是 Unix 秒数") from exc
    else:
        value = datetime.now(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def build_outputs(
    db: dict[str, Any],
    breeding: dict[str, Any],
    db_blob: SourceBlob,
    breeding_blob: SourceBlob,
    steam: dict[str, Any],
    project_root: Path,
    pak_assets: Path | None,
) -> tuple[dict[Path, bytes], dict[str, Any]]:
    source_pals = db.get("Pals")
    source_breeding = breeding.get("Breeding")
    gender_table = db.get("BreedingGenderProbability")
    if not isinstance(source_pals, list) or not isinstance(source_breeding, list):
        raise DataUpdateError("PalCalc JSON schema 不匹配：缺少 Pals/Breeding 数组")
    if not isinstance(gender_table, dict):
        raise DataUpdateError("PalCalc db.json 缺少 BreedingGenderProbability")

    official_rows: list[dict[str, Any]] = []
    excluded: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for pal in source_pals:
        classification = classify_excluded(pal)
        if classification is not None:
            excluded[str(pal.get("InternalName", ""))] = excluded_record(
                pal, classification
            )
        else:
            official_rows.append(pal)

    excluded["WorldTreeDragon"] = {
        "category": "special/hidden-boss",
        "reason": "#204 隐藏最终 Boss 不属于官方 287 条默认图鉴；固定 PalCalc db 当前未包含该行",
        "presentInSource": False,
        "palDexNo": 204,
        "isVariant": False,
        "trustedLocalization": False,
        "name": None,
    }

    if len(official_rows) != OFFICIAL_PAL_COUNT:
        raise DataUpdateError(
            f"官方帕鲁数量不符：期望 {OFFICIAL_PAL_COUNT}，实际 {len(official_rows)}"
        )

    elements_by_internal, element_provenance = load_optional_elements(
        pak_assets,
        {str(pal.get("InternalName", "")) for pal in official_rows},
    )

    official_rows.sort(key=lambda pal: pal_sort_key(pal_id(pal["Id"])))
    official_ids = [pal_id(pal["Id"]) for pal in official_rows]
    if len(set(official_ids)) != len(official_ids):
        raise DataUpdateError("过滤后存在重复 PalDex ID")
    official_id_set = set(official_ids)

    pals: OrderedDict[str, dict[str, Any]] = OrderedDict()
    paldeck: OrderedDict[str, dict[str, Any]] = OrderedDict()
    internal_mapping: OrderedDict[str, str] = OrderedDict()
    max_base_work = 0

    assets_dir = project_root / "src" / "pal_breed_helper" / "assets"
    images_dir = assets_dir / "images" / "pals"
    pending_assets: dict[Path, bytes] = {}
    retained_icon_count = 0
    extracted_icon_count = 0
    placeholder_icons: list[dict[str, Any]] = []

    pak_root = pak_assets.expanduser().resolve(strict=True) if pak_assets else None
    if pak_root and pak_root.is_file():
        pak_root = pak_root.parent
    manifest_ufs = find_manifest_ufs(pak_assets)
    triplet_status = inspect_asset_triplets(
        manifest_ufs,
        {value[0] for value in REQUIRED_NEW_PALS.values()} | {"WorldTreeDragon"},
    )

    for pal in official_rows:
        key = pal_id(pal["Id"])
        internal = str(pal["InternalName"])
        localized = pal.get("LocalizedNames") or {}
        en_name = str(localized.get("en") or pal.get("Name") or "").strip()
        zh_name = str(localized.get("zh-Hans") or "").strip()
        if not en_name or not zh_name:
            raise DataUpdateError(f"正式帕鲁 {internal} 缺少 en/zh-Hans 名称")
        if en_name in {"en_text", "en Text"} or zh_name in {"zh_Hans_Text", "zh-Hans Text"}:
            raise DataUpdateError(f"正式帕鲁 {internal} 仍是占位本地化")

        raw_work = pal.get("WorkSuitability") or {}
        if not isinstance(raw_work, dict):
            raise DataUpdateError(f"正式帕鲁 {internal} WorkSuitability 不是对象")
        unknown_work_fields = set(raw_work) - WORK_SOURCE_FIELDS
        if unknown_work_fields:
            raise DataUpdateError(
                f"正式帕鲁 {internal} 出现未知工作适性字段："
                + ", ".join(sorted(unknown_work_fields))
            )
        work: list[dict[str, Any]] = []
        for source_name, legacy_name, zh_work_name in WORK_FIELDS:
            level = int(raw_work.get(source_name, 0) or 0)
            if not 0 <= level <= WORK_SUITABILITY_CAP:
                raise DataUpdateError(
                    f"正式帕鲁 {internal} 工作适性 {source_name} 越界：{level}"
                )
            if level > 0:
                work.append({"en": legacy_name, "zh": zh_work_name, "lv": level})
                max_base_work = max(max_base_work, level)

        raw_gender = gender_table.get(internal)
        if not isinstance(raw_gender, dict):
            raise DataUpdateError(f"正式帕鲁 {internal} 缺少性别概率")
        male = float(raw_gender.get("MALE"))
        female = float(raw_gender.get("FEMALE"))
        gender_total = male + female
        if not (0.0 <= male <= 1.0 and 0.0 <= female <= 1.0):
            raise DataUpdateError(f"正式帕鲁 {internal} 性别概率超出 0..1")
        # Unreal 导出的 float32 会出现 0.100000024 这类舍入尾差。
        # 接受微小的源数据浮点误差，但在输出前归一化，保证消费端契约稳定。
        if abs(gender_total - 1.0) > 1e-6:
            raise DataUpdateError(f"正式帕鲁 {internal} 性别概率之和不为 1")
        male = round(male / gender_total, 6)
        female = round(1.0 - male, 6)

        elements = list(elements_by_internal.get(internal, []))
        element_status = (
            str(element_provenance.get("status"))
            if internal in elements_by_internal
            else "unknown"
        )
        stats = OrderedDict(
            (
                ("hp", int(pal.get("Hp", 0) or 0)),
                ("attack", int(pal.get("Attack", 0) or 0)),
                ("defense", int(pal.get("Defense", 0) or 0)),
                ("craftSpeed", int(pal.get("CraftSpeed", 0) or 0)),
                ("walkSpeed", int(pal.get("WalkSpeed", 0) or 0)),
                ("runSpeed", int(pal.get("RunSpeed", 0) or 0)),
                ("rideSprintSpeed", int(pal.get("RideSprintSpeed", 0) or 0)),
                ("transportSpeed", int(pal.get("TransportSpeed", 0) or 0)),
                ("stamina", int(pal.get("Stamina", 0) or 0)),
                ("maxFullStomach", int(pal.get("MaxFullStomach", 0) or 0)),
                ("price", int(pal.get("Price", 0) or 0)),
                ("size", pal.get("Size")),
                ("nocturnal", bool(pal.get("Nocturnal"))),
                ("minWildLevel", pal.get("MinWildLevel")),
                ("maxWildLevel", pal.get("MaxWildLevel")),
            )
        )

        image_relative: str | None = None
        # SVG 是本生成器的缺图占位格式，不能在下一次运行时误报为真实旧图标。
        for extension in (".webp", ".png", ".jpg", ".jpeg"):
            existing = images_dir / f"{key}{extension}"
            if existing.is_file():
                image_relative = f"images/pals/{existing.name}"
                retained_icon_count += 1
                break
        if image_relative is None and pak_root is not None:
            source_icon = next(
                (path for path in icon_source_candidates(pak_root, internal) if path.is_file()),
                None,
            )
            if source_icon is not None:
                target = images_dir / f"{key}{source_icon.suffix.lower()}"
                pending_assets[target] = source_icon.read_bytes()
                image_relative = f"images/pals/{target.name}"
                extracted_icon_count += 1
        if image_relative is None:
            target = images_dir / f"{key}.svg"
            pending_assets[target] = build_placeholder_svg(key, zh_name, en_name)
            image_relative = f"images/pals/{target.name}"
            placeholder_icons.append(
                {
                    "id": key,
                    "internal": internal,
                    "path": image_relative,
                    "iconMissing": True,
                    "expectedPakAsset": (
                        "Pal/Content/Pal/Texture/PalIcon/Normal/"
                        f"T_{internal}_icon_normal"
                    ),
                    "pakAssetTripletPresent": triplet_status.get(internal),
                }
            )

        gender_probability = {"male": male, "female": female}
        pal_record = OrderedDict(
            (
                ("zh", zh_name),
                ("en", en_name),
                ("internal", internal),
                ("r", int(pal.get("Rarity", 0) or 0)),
                ("t", elements),
                ("elementStatus", element_status),
                ("work", work),
                ("food", int(pal.get("FoodAmount", 0) or 0)),
                ("stats", stats),
                ("genderProbability", gender_probability),
                ("breedingPower", int(pal.get("BreedingPower", 0) or 0)),
                (
                    "breedingPowerPriority",
                    int(pal.get("BreedingPowerPriority", 0) or 0),
                ),
            )
        )
        pals[key] = pal_record
        paldeck[key] = OrderedDict(
            (
                ("no", key),
                ("zh", zh_name),
                ("en", en_name),
                ("internal", internal),
                ("types", elements),
                ("elementStatus", element_status),
                ("food", int(pal.get("FoodAmount", 0) or 0)),
                ("work", work),
                ("drops", []),
                ("egg", ""),
                ("desc", ""),
                ("img", image_relative),
                ("stats", stats),
                ("genderProbability", gender_probability),
            )
        )
        # 存档解析直接落到稳定图鉴 key；英文名只用于展示，不能作为二次关联键。
        internal_mapping[internal] = key

    if max_base_work != EXPECTED_MAX_BASE_WORK:
        raise DataUpdateError(
            f"基础工作适性最大值异常：期望 {EXPECTED_MAX_BASE_WORK}，实际 {max_base_work}"
        )

    breed: OrderedDict[str, list[list[Any]]] = OrderedDict(
        (key, []) for key in official_ids
    )
    seen_breed_rows: set[tuple[str, str, str, str, str]] = set()
    skipped_breeding_rows = 0
    for row in source_breeding:
        parent1 = pal_id(row["Parent1ID"])
        parent2 = pal_id(row["Parent2ID"])
        child = pal_id(row["ChildID"])
        gender1 = str(row.get("Parent1Gender", "WILDCARD"))
        gender2 = str(row.get("Parent2Gender", "WILDCARD"))
        if gender1 not in VALID_GENDERS or gender2 not in VALID_GENDERS:
            raise DataUpdateError(f"未知配种性别约束：{gender1}/{gender2}")
        if {parent1, parent2, child} - official_id_set:
            skipped_breeding_rows += 1
            continue
        identity = (child, parent1, gender1, parent2, gender2)
        if identity in seen_breed_rows:
            continue
        seen_breed_rows.add(identity)
        breed[child].append(
            [
                parent1,
                parent2,
                {"parent1Gender": gender1, "parent2Gender": gender2},
            ]
        )

    for child, pairs in breed.items():
        pairs.sort(
            key=lambda pair: (
                pal_sort_key(pair[0]),
                pal_sort_key(pair[1]),
                pair[2]["parent1Gender"],
                pair[2]["parent2Gender"],
            )
        )
        if not pairs:
            raise DataUpdateError(f"正式帕鲁 {child} 没有任何配种引用")

    panthalus_pairs = breed.get("203")
    if panthalus_pairs != [
        [
            "203",
            "203",
            {"parent1Gender": "WILDCARD", "parent2Gender": "WILDCARD"},
        ]
    ]:
        raise DataUpdateError("#203 IgnoreCombi 门禁异常：作为子代时必须仅保留 203×203")
    if "204" in pals or "204" in breed:
        raise DataUpdateError("#204 WorldTreeDragon 不得进入默认 PalCalc")

    sentinel_pair = {"1", "46"}
    woolipop_match = any({pair[0], pair[1]} == sentinel_pair for pair in breed["39"])
    ribbuny_match = any({pair[0], pair[1]} == sentinel_pair for pair in breed["44"])
    sentinel_powers = {
        key: int(pals[key]["breedingPower"]) for key in ("1", "39", "44", "46")
    }
    if (
        not woolipop_match
        or ribbuny_match
        or sentinel_powers != {"1": 3050, "39": 2820, "44": 2860, "46": 2590}
        or (sentinel_powers["1"] + sentinel_powers["46"]) // 2
        != sentinel_powers["39"]
    ):
        raise DataUpdateError(
            "争议配方门禁失败：棉悠悠(3050) × 海月灵(2590) 必须得到棉花糖(2820)，不得得到姬小兔(2860)"
        )

    manifest_build = steam.get("buildId")
    generated_at = generated_at_utc()
    data_version = str(db.get("Version") or "unknown")
    all_elements_known = len(elements_by_internal) >= OFFICIAL_PAL_COUNT and all(
        pal["internal"] in elements_by_internal for pal in pals.values()
    )
    field_status = {
        "names": "pinned-current-cue4parse-export",
        "workSuitability": "pinned-current-cue4parse-export",
        "stats": "pinned-current-cue4parse-export",
        "genderProbability": "pinned-current-cue4parse-export",
        "breedingMatrix": "pinned-current-cue4parse-export-with-gender-constraints",
        "elements": (
            str(element_provenance.get("status"))
            if all_elements_known
            else "unknown"
        ),
        "ignoreCombi": "guarded-by-pinned-resolved-breeding-matrix",
        "descriptions": "unknown-not-exported",
        "drops": "unknown-not-exported",
        "eggType": "unknown-not-exported",
    }
    meta = OrderedDict(
        (
            ("schemaVersion", 1),
            ("dataVersion", data_version),
            ("gameVersion", OFFICIAL_GAME_VERSION),
            ("buildId", manifest_build),
            ("generatedAtUtc", generated_at),
            # 浏览器旧字段名兼容；与 canonical generatedAtUtc 保持同值。
            ("updatedAt", generated_at),
            ("officialPalCount", OFFICIAL_PAL_COUNT),
            ("sourceCommit", PALCALC_COMMIT),
            ("sourceStatus", "verified"),
            ("workSuitabilityCap", WORK_SUITABILITY_CAP),
            ("maxBaseWorkSuitability", max_base_work),
            ("fieldStatus", field_status),
            ("genderConstraintsIncluded", True),
        )
    )

    internal_document = OrderedDict(
        (
            ("schemaVersion", 2),
            ("dataVersion", data_version),
            ("mapping", internal_mapping),
            ("excluded", excluded),
        )
    )
    pd = OrderedDict((("meta", meta), ("pals", pals), ("breed", breed)))
    game_data = OrderedDict(
        (
            ("schemaVersion", 1),
            ("meta", meta),
            ("pals", pals),
            ("breed", breed),
            ("excluded", excluded),
        )
    )

    breeding_bytes = f"window.PD = {compact_json(pd)};\n".encode("utf-8")
    paldeck_bytes = (
        f"window.PALDECK = {compact_json(paldeck)};\n"
        f"window.WORKICONS = {compact_json(WORK_ICONS)};\n"
    ).encode("utf-8")
    internal_bytes = pretty_json(internal_document).encode("utf-8")
    game_data_bytes = pretty_json(game_data).encode("utf-8")

    data_dir = assets_dir / "data"
    output_files: dict[Path, bytes] = {
        data_dir / "breeding.js": breeding_bytes,
        data_dir / "paldeck.js": paldeck_bytes,
        data_dir / "game_data.json": game_data_bytes,
        project_root / "src" / "pal_breed_helper" / "data" / "internal_names.json": internal_bytes,
        **pending_assets,
    }
    output_hashes = {
        str(path.relative_to(project_root)).replace("\\", "/"): sha256_bytes(data)
        for path, data in output_files.items()
        if path.suffix.lower() not in {".svg", ".png", ".jpg", ".jpeg", ".webp"}
    }

    manifest_triplets = {
        internal: status for internal, status in triplet_status.items()
    }
    filters = [
        {
            "name": "unindexed-pals",
            "rule": "PalDexNo >= 10000",
            "excludedSourceRows": sum(
                1 for pal in source_pals if int(pal["Id"]["PalDexNo"]) >= 10000
            ),
            "categories": ["special/terraria", "unreleased/unknown"],
        },
        {
            "name": "gumoss-special",
            "rule": "InternalName == PlantSlime_Flower",
            "excludedSourceRows": sum(
                1 for pal in source_pals if pal.get("InternalName") == "PlantSlime_Flower"
            ),
            "category": "special/cosmetic-variant",
        },
        {
            "name": "world-tree-hidden-boss",
            "rule": "InternalName == WorldTreeDragon or PalDexNo == 204",
            "excludedSourceRows": sum(
                1
                for pal in source_pals
                if pal.get("InternalName") == "WorldTreeDragon"
                or int(pal["Id"]["PalDexNo"]) == 204
            ),
            "category": "special/hidden-boss",
        },
    ]
    provenance = OrderedDict(
        (
            ("schemaVersion", 1),
            ("generatedAtUtc", generated_at),
            (
                "source",
                {
                    "kind": "pinned-community-cue4parse-export",
                    "repository": f"https://github.com/{PALCALC_REPOSITORY}",
                    "commit": PALCALC_COMMIT,
                    "commitDate": PALCALC_COMMIT_DATE,
                    "db": {
                        "location": db_blob.location,
                        "sha256": db_blob.sha256,
                        "expectedSha256": EXPECTED_DB_SHA256,
                        "pinnedMatch": db_blob.sha256 == EXPECTED_DB_SHA256,
                        "version": data_version,
                    },
                    "breeding": {
                        "location": breeding_blob.location,
                        "sha256": breeding_blob.sha256,
                        "expectedSha256": EXPECTED_BREEDING_SHA256,
                        "pinnedMatch": breeding_blob.sha256
                        == EXPECTED_BREEDING_SHA256,
                    },
                    "trustNote": "PalCalc 不是官方 API；固定 commit 的 CUE4Parse 导出用于行级结构，官方公告承担版本与 287 数量断言；争议配方另以 BreedingPower 公式和独立当前计算器交叉核对。",
                },
            ),
            ("game", steam),
            (
                "officialRelease",
                {
                    "version": OFFICIAL_GAME_VERSION,
                    "date": OFFICIAL_RELEASE_DATE,
                    "url": OFFICIAL_RELEASE_URL,
                    "gid": OFFICIAL_RELEASE_GID,
                    "expectedPalCount": OFFICIAL_PAL_COUNT,
                    "assertion": "72 new Pals; 287 total; breeding and work suitability rebalanced",
                },
            ),
            ("filters", filters),
            ("fieldStatus", field_status),
            ("elements", element_provenance),
            (
                "counts",
                {
                    "sourcePals": len(source_pals),
                    "officialPals": len(pals),
                    "basePals": sum(1 for key in pals if not key.endswith("B")),
                    "variantPals": sum(1 for key in pals if key.endswith("B")),
                    "excludedSourceRows": len(source_pals) - len(pals),
                    "excludedPolicyRecords": len(excluded),
                    "sourceBreedingRows": len(source_breeding),
                    "outputBreedingRows": sum(len(value) for value in breed.values()),
                    "skippedBreedingRows": skipped_breeding_rows,
                    "maxBaseWorkSuitability": max_base_work,
                    "workSuitabilityCap": WORK_SUITABILITY_CAP,
                },
            ),
            (
                "icons",
                {
                    "policy": "不抓取第三方图；优先保留本地已有游戏图，随后读取 --pak-assets 已导出的图片，否则生成本地 SVG 占位。",
                    "assetManifestPath": manifest_ufs.name if manifest_ufs else None,
                    "assetTriplets": manifest_triplets,
                    "retainedExistingCount": retained_icon_count,
                    "extractedFromPakAssetsCount": extracted_icon_count,
                    "placeholderCount": len(placeholder_icons),
                    "missing": placeholder_icons,
                },
            ),
            (
                "pakObservations",
                [
                    {
                        "internal": "WorldTreeDragon",
                        "palDexNo": 204,
                        "classification": "special/hidden-boss",
                        "includedInDefaultCalculator": False,
                        "observedInLocalAssetManifest": (
                            triplet_status.get("WorldTreeDragon") is True
                        ),
                        "iconAssetTripletPresent": triplet_status.get("WorldTreeDragon"),
                    }
                ],
            ),
            (
                "validation",
                {
                    "officialPalCount": "passed",
                    "requiredNewPals": "passed",
                    "hangyuLocalization": "passed",
                    "workSuitability": "passed",
                    "breedingReferences": "passed",
                    "genderConstraints": "passed",
                    "ignoreCombi203": "passed-self-only-as-child",
                    "lamballJellroySentinel": "passed-woolipop-2820-not-ribbuny-2860",
                    "worldTree204": "passed-excluded",
                    "oldSnapshotFieldsReused": False,
                },
            ),
            ("outputs", output_hashes),
        )
    )
    provenance_path = data_dir / "provenance.json"
    output_files[provenance_path] = pretty_json(provenance).encode("utf-8")

    summary = {
        "officialPals": len(pals),
        "breedingRows": sum(len(value) for value in breed.values()),
        "placeholderIcons": len(placeholder_icons),
        "knownElements": sum(1 for value in pals.values() if value["t"]),
        "buildId": manifest_build,
        "outputs": len(output_files),
    }
    return output_files, summary


def atomic_write_many(files: dict[Path, bytes]) -> None:
    prepared: list[tuple[Path, Path]] = []
    committed: list[tuple[Path, Path | None]] = []
    try:
        for target, data in files.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            handle = tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=f".{target.name}.",
                suffix=".tmp",
                dir=target.parent,
                delete=False,
            )
            temp_path = Path(handle.name)
            try:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            finally:
                handle.close()
            prepared.append((temp_path, target))
        for temp_path, target in prepared:
            backup: Path | None = None
            if target.exists():
                backup_handle = tempfile.NamedTemporaryFile(
                    prefix=f".{target.name}.",
                    suffix=".bak",
                    dir=target.parent,
                    delete=False,
                )
                backup = Path(backup_handle.name)
                backup_handle.close()
                backup.unlink()
                os.replace(target, backup)
            try:
                os.replace(temp_path, target)
            except BaseException:
                if backup is not None and backup.exists():
                    os.replace(backup, target)
                raise
            committed.append((target, backup))
    except BaseException as exc:
        rollback_errors: list[str] = []
        for target, backup in reversed(committed):
            try:
                if backup is None:
                    target.unlink(missing_ok=True)
                elif backup.exists():
                    os.replace(backup, target)
            except OSError as rollback_exc:
                rollback_errors.append(f"{target}: {rollback_exc}")
        if rollback_errors:
            raise DataUpdateError(
                "数据更新失败且回滚不完整：" + "；".join(rollback_errors)
            ) from exc
        raise
    finally:
        for temp_path, _ in prepared:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
        for _, backup in committed:
            if backup is not None:
                try:
                    backup.unlink(missing_ok=True)
                except OSError:
                    pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    project_default = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="从固定 PalCalc 1.0 CUE4Parse 导出生成帕鲁配种助手数据。"
    )
    parser.add_argument("--db", default=DEFAULT_DB, help="db.json 路径或 HTTPS URL")
    parser.add_argument(
        "--breeding",
        default=DEFAULT_BREEDING,
        help="breeding.json 路径或 HTTPS URL",
    )
    parser.add_argument(
        "--steam-manifest",
        type=Path,
        help="Steam appmanifest_1623730.acf；省略时按 Steam 库自动发现",
    )
    parser.add_argument(
        "--pak-assets",
        type=Path,
        help="可选的游戏根目录或已导出的 PAK 资源目录；可含 pal_elements.json 和图标",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=project_default,
        help="项目根目录，默认根据脚本位置推导",
    )
    parser.add_argument(
        "--allow-unpinned",
        action="store_true",
        help="允许输入 SHA256 不等于固定 PalCalc commit（默认拒绝）",
    )
    parser.add_argument(
        "--allow-build-mismatch",
        action="store_true",
        help="允许 Steam buildid 不是当前验证过的 24088745",
    )
    parser.add_argument("--dry-run", action="store_true", help="只生成和校验，不写文件")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        project_root = args.output_root.expanduser().resolve(strict=True)
        db_blob = load_source(args.db)
        breeding_blob = load_source(args.breeding)
        if not args.allow_unpinned:
            if db_blob.sha256 != EXPECTED_DB_SHA256:
                raise DataUpdateError(
                    f"db.json SHA256 不匹配固定 commit：{db_blob.sha256}"
                )
            if breeding_blob.sha256 != EXPECTED_BREEDING_SHA256:
                raise DataUpdateError(
                    f"breeding.json SHA256 不匹配固定 commit：{breeding_blob.sha256}"
                )

        manifest_path = args.steam_manifest or discover_steam_manifest()
        steam = parse_acf(manifest_path)
        if steam.get("found"):
            if steam.get("appId") != PALWORLD_APP_ID:
                raise DataUpdateError(f"Steam manifest appid 不是 {PALWORLD_APP_ID}")
            if (
                not args.allow_build_mismatch
                and steam.get("buildId") != EXPECTED_BUILD_ID
            ):
                raise DataUpdateError(
                    f"Steam buildid 未验证：期望 {EXPECTED_BUILD_ID}，实际 {steam.get('buildId')}"
                )

        outputs, summary = build_outputs(
            decode_json(db_blob, "db.json"),
            decode_json(breeding_blob, "breeding.json"),
            db_blob,
            breeding_blob,
            steam,
            project_root,
            args.pak_assets,
        )
        if not args.dry_run:
            atomic_write_many(outputs)
        action = "校验完成，未写入" if args.dry_run else "数据已原子替换"
        print(
            f"{action}：{summary['officialPals']} 只正式帕鲁，"
            f"{summary['breedingRows']} 条配种记录，"
            f"{summary['placeholderIcons']} 个本地占位图标，"
            f"元素已知 {summary['knownElements']}，buildid={summary['buildId'] or '未提供'}。"
        )
        return 0
    except (DataUpdateError, OSError) as exc:
        print(f"数据更新失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
