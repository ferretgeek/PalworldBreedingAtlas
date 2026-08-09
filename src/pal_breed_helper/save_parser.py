from __future__ import annotations

import collections
import ctypes
import hashlib
import json
import os
import re
import shutil
import string
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Iterable


APP_DATA_DIR_NAME = "PalBreedHelper"
CACHE_FILE_NAME = ".palhelper_cache.json"
OWNED_FILE_NAME = "owned-pals.json"
GENERATED_HTML_NAME = "帕鲁配种_已载入存档.html"
GENERATED_DIR_NAME = "generated"
MAX_UNCOMPRESSED_BYTES = int(
    os.environ.get("PAL_HELPER_MAX_UNCOMPRESSED_BYTES", 2 * 1024 * 1024 * 1024)
)

_cache: dict | None = None
_cache_lock = threading.RLock()
_mapping_cache: tuple[tuple[int, int], tuple[int, int], dict, dict] | None = None
_breeding_cache: tuple[tuple[int, int], dict] | None = None


class OperationCancelled(RuntimeError):
    """后台任务被用户取消。"""


def _check_cancel(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise OperationCancelled("操作已取消。")


def package_dir() -> Path:
    return Path(__file__).resolve().parent


def asset_dir() -> Path:
    if getattr(sys, "frozen", False):
        frozen_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        packaged = frozen_root / "pal_breed_helper" / "assets"
        if packaged.is_dir():
            return packaged
        fallback = frozen_root / "assets"
        if fallback.is_dir():
            return fallback
    return package_dir() / "assets"


def data_dir() -> Path:
    if getattr(sys, "frozen", False):
        frozen_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        packaged = frozen_root / "pal_breed_helper" / "data"
        if packaged.is_dir():
            return packaged
        fallback = frozen_root / "data"
        if fallback.is_dir():
            return fallback
    return package_dir() / "data"


def output_dir() -> Path:
    override = os.environ.get("PAL_BREED_HELPER_DATA_DIR")
    if override:
        target = resolved_path(override)
        target.mkdir(parents=True, exist_ok=True)
        return target
    if getattr(sys, "frozen", False):
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            target = Path(base) / APP_DATA_DIR_NAME
            try:
                target.mkdir(parents=True, exist_ok=True)
                return target
            except OSError:
                pass
        fallback = Path(tempfile.gettempdir()) / APP_DATA_DIR_NAME
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback
    target = package_dir().parents[1] / ".runtime"
    target.mkdir(parents=True, exist_ok=True)
    return target


def cache_path() -> Path:
    return output_dir() / CACHE_FILE_NAME


def owned_json_path() -> Path:
    return output_dir() / OWNED_FILE_NAME


def resolved_path(path: str | os.PathLike[str], strict: bool = False) -> Path:
    expanded = os.path.expandvars(os.path.expanduser(os.fspath(path)))
    candidate = Path(expanded)
    try:
        return candidate.resolve(strict=strict)
    except (OSError, RuntimeError):
        return Path(os.path.abspath(os.path.normpath(str(candidate))))


def normalize_path(path: str | os.PathLike[str], strict: bool = False) -> str:
    return os.path.normpath(str(resolved_path(path, strict=strict)))


def path_key(path: str | os.PathLike[str]) -> str:
    return os.path.normcase(normalize_path(path, strict=False))


def _atomic_write_text(target: Path, text: str, encoding: str = "utf-8") -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding=encoding,
            newline="",
            delete=False,
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
        ) as output:
            temporary = Path(output.name)
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def atomic_write_json(
    target: str | os.PathLike[str], data: object, *, indent: int | None = None
) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=indent)
    if indent is not None:
        text += "\n"
    _atomic_write_text(Path(target), text)


def atomic_write_text(target: str | os.PathLike[str], text: str) -> None:
    _atomic_write_text(Path(target), text)


def read_json_object(path: str | os.PathLike[str]) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _coerce_cache(value: object) -> dict:
    if not isinstance(value, dict):
        value = {}
    result: dict = {"oodle": None, "meta": {}, "save_roots": []}

    oodle = value.get("oodle")
    if isinstance(oodle, str) and oodle.strip():
        result["oodle"] = normalize_path(oodle)

    meta = value.get("meta")
    if isinstance(meta, dict):
        for raw_key, raw_info in meta.items():
            if not isinstance(raw_key, str) or not isinstance(raw_info, dict):
                continue
            result["meta"][path_key(raw_key)] = dict(raw_info)

    roots = value.get("save_roots")
    if isinstance(roots, list):
        seen: set[str] = set()
        for raw_root in roots:
            if not isinstance(raw_root, str) or not raw_root.strip():
                continue
            root = normalize_path(raw_root)
            key = path_key(root)
            if key not in seen:
                seen.add(key)
                result["save_roots"].append(root)
    return result


def _cache_load() -> dict:
    global _cache
    with _cache_lock:
        if _cache is None:
            _cache = _coerce_cache(read_json_object(cache_path()))
        return _cache


def _cache_save() -> None:
    with _cache_lock:
        if _cache is None:
            return
        try:
            atomic_write_json(cache_path(), _cache)
        except OSError:
            pass


def _file_signature(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def breeding_data() -> dict:
    global _breeding_cache
    path = asset_dir() / "data" / "breeding.js"
    signature = _file_signature(path)
    if _breeding_cache is not None and _breeding_cache[0] == signature:
        return _breeding_cache[1]
    text = path.read_text(encoding="utf-8")
    marker = "window.PD = "
    start = text.index(marker) + len(marker)
    value, _ = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(value, dict):
        raise RuntimeError("配种数据格式不正确。")
    _breeding_cache = (signature, value)
    return value


def data_provenance() -> dict:
    path = asset_dir() / "data" / "provenance.json"
    if path.is_file():
        value = read_json_object(path)
        if value:
            return value
    data = breeding_data()
    for key in ("meta", "metadata", "provenance"):
        value = data.get(key)
        if isinstance(value, dict):
            return value
    return {}


def data_status() -> dict:
    data = breeding_data()
    provenance = data_provenance()
    release = provenance.get("officialRelease")
    game = provenance.get("game")
    counts = provenance.get("counts")
    release = release if isinstance(release, dict) else {}
    game = game if isinstance(game, dict) else {}
    counts = counts if isinstance(counts, dict) else {}
    version = str(
        release.get("version")
        or provenance.get("gameVersion")
        or data.get("version")
        or "未标注"
    )
    build_id = str(game.get("buildId") or provenance.get("buildId") or "").strip()
    pal_count = counts.get("officialPals") or counts.get("pals")
    if not isinstance(pal_count, int):
        pal_count = len(data.get("pals", {}))
    generated = str(
        provenance.get("generatedAtUtc") or provenance.get("generatedAt") or ""
    ).strip()
    source = provenance.get("source")
    validation = provenance.get("validation")
    source = source if isinstance(source, dict) else {}
    validation = validation if isinstance(validation, dict) else {}
    pinned_values: list[bool] = []
    for key in ("db", "breeding"):
        source_item = source.get(key)
        if isinstance(source_item, dict) and "pinnedMatch" in source_item:
            pinned_values.append(bool(source_item.get("pinnedMatch")))
    count_validation = str(validation.get("officialPalCount") or "").lower()
    verified = bool(source and release and generated)
    if pinned_values and not all(pinned_values):
        verified = False
    if count_validation and not count_validation.startswith("passed"):
        verified = False
    return {
        "version": version,
        "buildId": build_id,
        "palCount": pal_count,
        "generatedAt": generated,
        "verified": verified,
        "provenance": provenance,
    }


def _mapping_payload(raw: object) -> tuple[dict, dict]:
    if not isinstance(raw, dict):
        return {}, {}
    wrapper_keys = (
        "mapping",
        "mappings",
        "internalToKey",
        "internal_to_key",
        "internalNames",
    )
    mapping: object = None
    for key in wrapper_keys:
        if key in raw:
            mapping = raw.get(key)
            break
    if mapping is None:
        metadata_keys = {
            "schemaVersion",
            "metadata",
            "meta",
            "excluded",
            "ignored",
        }
        mapping = {key: value for key, value in raw.items() if key not in metadata_keys}
    if not isinstance(mapping, dict):
        mapping = {}
    excluded = raw.get("excluded") or raw.get("ignored") or {}
    if not isinstance(excluded, dict):
        excluded = {}
    return mapping, excluded


def _mapping_value_to_key(
    value: object, pals: dict, english_to_key: dict[str, str]
) -> str | None:
    if isinstance(value, dict):
        for field in ("key", "palKey", "stableKey", "id"):
            candidate = value.get(field)
            if candidate is not None and str(candidate) in pals:
                return str(candidate)
        name = value.get("english") or value.get("en") or value.get("name")
        if isinstance(name, dict):
            name = name.get("en")
        value = name
    if value is None:
        return None
    text = str(value).strip()
    if text in pals:
        return text
    return english_to_key.get(text.lower().replace(" ", ""))


def _load_internal_schema() -> tuple[dict[str, str], dict[str, dict]]:
    global _mapping_cache
    mapping_path = data_dir() / "internal_names.json"
    breeding_path = asset_dir() / "data" / "breeding.js"
    mapping_signature = _file_signature(mapping_path)
    breeding_signature = _file_signature(breeding_path)
    if (
        _mapping_cache is not None
        and _mapping_cache[0] == mapping_signature
        and _mapping_cache[1] == breeding_signature
    ):
        return _mapping_cache[2], _mapping_cache[3]

    raw = json.loads(mapping_path.read_text(encoding="utf-8"))
    mapping, excluded = _mapping_payload(raw)
    pals = breeding_data().get("pals", {})
    if not isinstance(pals, dict):
        raise RuntimeError("配种数据缺少 pals。")
    english_to_key, _ = load_en_to_key()

    resolved: dict[str, str] = {}
    for internal, value in mapping.items():
        if not isinstance(internal, str):
            continue
        key = _mapping_value_to_key(value, pals, english_to_key)
        if key:
            resolved[internal.lower()] = key

    excluded_view: dict[str, dict] = {}
    for internal, value in excluded.items():
        if not isinstance(internal, str):
            continue
        if isinstance(value, dict):
            info = dict(value)
        else:
            info = {"category": "special", "reason": str(value)}
        excluded_view[internal.lower()] = info

    _mapping_cache = (
        mapping_signature,
        breeding_signature,
        resolved,
        excluded_view,
    )
    return resolved, excluded_view


def internal_to_english() -> dict:
    raw = json.loads((data_dir() / "internal_names.json").read_text(encoding="utf-8"))
    mapping, _ = _mapping_payload(raw)
    return mapping


def _steam_roots() -> set[Path]:
    roots: set[Path] = set()
    try:
        import winreg

        registry_values = (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
            (
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\WOW6432Node\Valve\Steam",
                "InstallPath",
            ),
        )
        for hive, subkey, value_name in registry_values:
            try:
                with winreg.OpenKey(hive, subkey) as key:
                    roots.add(Path(winreg.QueryValueEx(key, value_name)[0]))
            except OSError:
                continue
    except Exception:
        pass

    common_paths = (
        r"Program Files (x86)\Steam",
        "Steam",
        "SteamLibrary",
        r"Games\Steam",
    )
    for letter in string.ascii_uppercase:
        drive = Path(f"{letter}:\\")
        if drive.is_dir():
            roots.update(drive / relative for relative in common_paths)

    libraries = set(roots)
    for root in list(roots):
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if not vdf.is_file():
            continue
        try:
            text = vdf.read_text(encoding="utf-8", errors="ignore")
            for match in re.finditer(r'"path"\s*"([^"]+)"', text):
                libraries.add(Path(match.group(1).replace(r"\\", "\\")))
        except OSError:
            pass
    return libraries


def find_oodle_dll(cancel_event: threading.Event | None = None) -> str | None:
    _check_cancel(cancel_event)
    if sys.platform != "win32":
        try:
            import palooz  # type: ignore[import-not-found]  # noqa: F401
        except ImportError:
            return None
        return "palooz"

    bundled = asset_dir() / "oo2core_9_win64.dll"
    if bundled.is_file():
        return normalize_path(bundled)

    cached = _cache_load().get("oodle")
    if isinstance(cached, str) and Path(cached).is_file():
        return normalize_path(cached)

    found = _find_oodle_dll_uncached(cancel_event)
    if found:
        with _cache_lock:
            _cache_load()["oodle"] = found
            _cache_save()
    return found


def _find_oodle_dll_uncached(
    cancel_event: threading.Event | None = None,
) -> str | None:
    relative_options = (
        Path("steamapps/common/Palworld/Pal/Binaries/Win64"),
        Path("Pal/Binaries/Win64"),
    )
    for root in _steam_roots():
        _check_cancel(cancel_event)
        for relative in relative_options:
            directory = root / relative
            try:
                hit = next(directory.glob("oo2core_*_win64.dll"), None)
            except OSError:
                hit = None
            if hit is not None and hit.is_file():
                return normalize_path(hit)
    return None


def _read_stable_bytes(
    path: str | os.PathLike[str],
    cancel_event: threading.Event | None = None,
    attempts: int = 3,
    retry_delay: float = 0.08,
) -> bytes:
    target = resolved_path(path, strict=False)
    last_error: BaseException | None = None
    for attempt in range(max(attempts, 1)):
        _check_cancel(cancel_event)
        try:
            before = target.stat()
            with target.open("rb") as source:
                data = source.read()
            after = target.stat()
            stable = (
                before.st_size == after.st_size == len(data)
                and before.st_mtime_ns == after.st_mtime_ns
            )
            if stable:
                return data
            last_error = RuntimeError("文件在读取期间发生变化。")
        except OSError as exc:
            last_error = exc
        if attempt + 1 < max(attempts, 1):
            if cancel_event is not None:
                if cancel_event.wait(retry_delay):
                    raise OperationCancelled("操作已取消。")
            else:
                time.sleep(retry_delay)
    raise RuntimeError(f"存档正在变化或暂时无法读取：{target}") from last_error


def decompress_sav(
    path: str | os.PathLike[str],
    dll_path: str | None,
    cancel_event: threading.Event | None = None,
) -> bytes:
    data = _read_stable_bytes(path, cancel_event)
    if len(data) < 12:
        raise RuntimeError("存档文件过短，无法读取。")

    uncompressed_size = int.from_bytes(data[0:4], "little")
    compressed_size = int.from_bytes(data[4:8], "little")
    magic = data[8:11]
    save_type = data[11]
    body = data[12:]

    if uncompressed_size <= 0:
        raise RuntimeError("存档声明的解压尺寸无效。")
    if uncompressed_size > MAX_UNCOMPRESSED_BYTES:
        raise RuntimeError(
            f"存档声明的解压尺寸过大：{uncompressed_size:,} 字节。"
        )
    _check_cancel(cancel_event)
    if magic == b"PlZ":
        if save_type not in (0x00, 0x31, 0x32):
            raise RuntimeError(f"不支持的 zlib 存档类型: 0x{save_type:02X}")
        import zlib

        if save_type == 0x32:
            intermediate = zlib.decompress(body)
            # In the double-zlib format this header field describes the
            # decompressed outer layer, not the on-disk body length.
            if compressed_size not in (0, len(intermediate)):
                raise RuntimeError(
                    "zlib 中间层长度异常："
                    f"{len(intermediate)} != {compressed_size}"
                )
            raw = zlib.decompress(intermediate)
        else:
            if compressed_size not in (0, len(body)):
                raise RuntimeError(
                    f"存档压缩长度异常：{compressed_size} != {len(body)}"
                )
            raw = zlib.decompress(body)
        if len(raw) != uncompressed_size:
            raise RuntimeError(
                f"zlib 解压字节数异常: {len(raw)} != {uncompressed_size}"
            )
        _check_cancel(cancel_event)
        return raw

    if magic != b"PlM":
        raise RuntimeError(f"未知存档魔数: {magic!r}")
    if save_type != 0x31:
        raise RuntimeError(f"不支持的 Oodle 存档类型: 0x{save_type:02X}")
    if compressed_size not in (0, len(body)):
        raise RuntimeError(
            f"存档压缩长度异常：{compressed_size} != {len(body)}"
        )
    if sys.platform != "win32":
        try:
            import palooz  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "当前系统缺少 palooz Oodle 解压后端，无法读取新版存档。"
            ) from exc
        try:
            raw = palooz.decompress(body, uncompressed_size)
        except Exception as exc:
            raise RuntimeError(f"Oodle 解压失败：{exc}") from exc
        if not isinstance(raw, (bytes, bytearray, memoryview)):
            raise RuntimeError("Oodle 解压后端返回了无效数据。")
        raw = bytes(raw)
        if len(raw) != uncompressed_size:
            raise RuntimeError(
                f"Oodle 解压字节数异常: {len(raw)} != {uncompressed_size}"
            )
        _check_cancel(cancel_event)
        return raw

    if not dll_path:
        raise RuntimeError(
            "找不到 Oodle DLL（oo2core_*_win64.dll），无法解压新版存档。"
        )

    oodle = ctypes.WinDLL(dll_path)
    decompress = oodle.OodleLZ_Decompress
    decompress.restype = ctypes.c_int64
    decompress.argtypes = [
        ctypes.c_char_p,
        ctypes.c_int64,
        ctypes.c_char_p,
        ctypes.c_int64,
        ctypes.c_int32,
        ctypes.c_int32,
        ctypes.c_int32,
        ctypes.c_void_p,
        ctypes.c_int64,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_int64,
        ctypes.c_int32,
    ]
    try:
        output = ctypes.create_string_buffer(uncompressed_size)
    except (MemoryError, OverflowError) as exc:
        raise RuntimeError("没有足够内存解压该存档。") from exc
    written = decompress(
        body,
        len(body),
        output,
        uncompressed_size,
        1,
        0,
        0,
        None,
        0,
        None,
        None,
        None,
        0,
        3,
    )
    _check_cancel(cancel_event)
    if written != uncompressed_size:
        raise RuntimeError(f"Oodle 解压字节数异常: {written} != {uncompressed_size}")
    return output.raw[:written]


def extract_species(raw: bytes) -> collections.Counter[str]:
    needle = b"CharacterID\x00\r\x00\x00\x00NameProperty\x00"
    counter: collections.Counter[str] = collections.Counter()
    offset = 0
    raw_length = len(raw)
    while True:
        found = raw.find(needle, offset)
        if found < 0:
            return counter
        cursor = found + len(needle) + 8 + 1
        if cursor + 4 > raw_length:
            return counter
        string_length = int.from_bytes(
            raw[cursor : cursor + 4], "little", signed=True
        )
        cursor += 4
        value = ""
        if 0 < string_length <= 256 and cursor + string_length <= raw_length:
            value = raw[cursor : cursor + string_length - 1].decode(
                "ascii", errors="replace"
            )
        elif (
            -256 <= string_length < 0
            and cursor + (-string_length * 2) <= raw_length
        ):
            value = raw[cursor : cursor + (-string_length * 2) - 2].decode(
                "utf-16-le", errors="replace"
            )
        if value:
            counter[value] += 1
        offset = found + len(needle)


def _read_fstring_at(raw: bytes, cursor: int, *, limit: int = 4096) -> tuple[str, int] | None:
    if cursor < 0 or cursor + 4 > len(raw):
        return None
    length = int.from_bytes(raw[cursor : cursor + 4], "little", signed=True)
    cursor += 4
    if length == 0:
        return "", cursor
    if 0 < length <= limit and cursor + length <= len(raw):
        return raw[cursor : cursor + length - 1].decode("utf-8", errors="replace"), cursor + length
    char_count = -length
    byte_count = char_count * 2
    if 0 < char_count <= limit and cursor + byte_count <= len(raw):
        return raw[cursor : cursor + byte_count - 2].decode("utf-16-le", errors="replace"), cursor + byte_count
    return None


def _property_header(region: bytes, key: str) -> tuple[str, int, int] | None:
    marker = key.encode("ascii") + b"\x00"
    offset = region.find(marker)
    if offset < 0:
        return None
    parsed_type = _read_fstring_at(region, offset + len(marker), limit=128)
    if parsed_type is None:
        return None
    property_type, cursor = parsed_type
    if cursor + 8 > len(region):
        return None
    size = int.from_bytes(region[cursor : cursor + 8], "little", signed=False)
    return property_type, cursor + 8, size


def _find_property_payload(
    raw: bytes, key: str, expected_type: str
) -> bytes | None:
    """返回顶层属性声明的严格 payload，避免扫描同文件中的历史/嵌套记录。"""
    encoded_key = key.encode("ascii") + b"\x00"
    marker = len(encoded_key).to_bytes(4, "little", signed=True) + encoded_key
    candidates: list[bytes] = []
    malformed: list[str] = []
    offset = 0
    while True:
        found = raw.find(marker, offset)
        if found < 0:
            break
        offset = found + len(marker)
        try:
            parsed_name = _read_fstring_at(raw, found, limit=256)
            if parsed_name is None or parsed_name[0] != key:
                continue
            parsed_type = _read_fstring_at(raw, parsed_name[1], limit=128)
            if parsed_type is None or parsed_type[0] != expected_type:
                continue
            cursor = parsed_type[1]
            if cursor + 8 > len(raw):
                raise ValueError("属性长度字段不完整")
            size = int.from_bytes(raw[cursor : cursor + 8], "little", signed=False)
            cursor += 8

            if expected_type == "MapProperty":
                key_type = _read_fstring_at(raw, cursor, limit=128)
                if key_type is None:
                    raise ValueError("MapProperty key type 不完整")
                value_type = _read_fstring_at(raw, key_type[1], limit=128)
                if value_type is None:
                    raise ValueError("MapProperty value type 不完整")
                cursor = value_type[1]
            elif expected_type == "ArrayProperty":
                inner_type = _read_fstring_at(raw, cursor, limit=128)
                if inner_type is None:
                    raise ValueError("ArrayProperty inner type 不完整")
                cursor = inner_type[1]
            elif expected_type == "StructProperty":
                struct_type = _read_fstring_at(raw, cursor, limit=256)
                if struct_type is None or struct_type[1] + 16 > len(raw):
                    raise ValueError("StructProperty metadata 不完整")
                cursor = struct_type[1] + 16

            if cursor >= len(raw) or raw[cursor] not in (0, 1):
                raise ValueError("属性 GUID 标记无效")
            has_property_guid = raw[cursor]
            cursor += 1
            if has_property_guid:
                if cursor + 16 > len(raw):
                    raise ValueError("属性 GUID 不完整")
                cursor += 16

            end = cursor + size
            if end > len(raw):
                raise ValueError("属性 payload 越界")
            next_property = _read_fstring_at(raw, end, limit=256)
            if next_property is None or not next_property[0]:
                raise ValueError("属性 payload 端点无效")
            candidates.append(raw[cursor:end])
        except ValueError as exc:
            malformed.append(str(exc))

    if len(candidates) > 1:
        raise RuntimeError(f"存档中的 {key} {expected_type} 属性不唯一。")
    if candidates:
        return candidates[0]
    if malformed:
        raise RuntimeError(f"存档中的 {key} 属性损坏：{malformed[0]}。")
    return None


def _world_character_payload(raw: bytes) -> bytes:
    payload = _find_property_payload(raw, "CharacterSaveParameterMap", "MapProperty")
    if payload is None:
        raise RuntimeError("存档缺少 CharacterSaveParameterMap，无法确认当前仍存在的帕鲁。")
    return payload


def _global_gene_payload(raw: bytes) -> bytes:
    payload = _find_property_payload(raw, "SaveParameterArray", "ArrayProperty")
    if payload is None:
        raise RuntimeError("跨界基因文件缺少 SaveParameterArray。")
    if len(payload) < 4:
        raise RuntimeError("跨界基因 SaveParameterArray 过短。")
    declared_slots = int.from_bytes(payload[:4], "little", signed=True)
    if declared_slots < 0:
        raise RuntimeError("跨界基因槽位数量无效。")
    parsed_slots = sum(extract_species(payload).values())
    if parsed_slots != declared_slots:
        raise RuntimeError(
            f"跨界基因槽位解析不完整：声明 {declared_slots}，识别 {parsed_slots}。"
        )
    return payload


def _read_name_property(region: bytes, key: str) -> str | None:
    header = _property_header(region, key)
    if header is None or header[0] != "NameProperty":
        return None
    cursor = header[1]
    if cursor >= len(region):
        return None
    parsed = _read_fstring_at(region, cursor + 1)
    return parsed[0] if parsed is not None else None


def _read_enum_property(region: bytes, key: str) -> str | None:
    header = _property_header(region, key)
    if header is None or header[0] != "EnumProperty":
        return None
    enum_type = _read_fstring_at(region, header[1], limit=256)
    if enum_type is None or enum_type[1] >= len(region):
        return None
    value = _read_fstring_at(region, enum_type[1] + 1, limit=256)
    if value is None:
        return None
    return value[0].rsplit("::", 1)[-1]


def _read_byte_property(region: bytes, key: str) -> int | None:
    header = _property_header(region, key)
    if header is None or header[0] != "ByteProperty":
        return None
    enum_type = _read_fstring_at(region, header[1], limit=256)
    if enum_type is None:
        return None
    cursor = enum_type[1] + 1
    if cursor >= len(region):
        return None
    return region[cursor]


def _read_name_array_property(region: bytes, key: str) -> list[str]:
    header = _property_header(region, key)
    if header is None or header[0] != "ArrayProperty":
        return []
    inner_type = _read_fstring_at(region, header[1], limit=128)
    if inner_type is None or inner_type[0] != "NameProperty":
        return []
    cursor = inner_type[1] + 1
    if cursor + 4 > len(region):
        return []
    count = int.from_bytes(region[cursor : cursor + 4], "little", signed=True)
    cursor += 4
    if count < 0 or count > 64:
        return []
    values: list[str] = []
    for _ in range(count):
        parsed = _read_fstring_at(region, cursor, limit=256)
        if parsed is None:
            return []
        value, cursor = parsed
        if value and value.lower() != "none":
            values.append(value)
    return values


def extract_individuals(raw: bytes, source: str = "world") -> list[dict]:
    """从 1.0 SaveParameter 记录中提取可验证的个体字段。"""
    needle = b"CharacterID\x00\r\x00\x00\x00NameProperty\x00"
    offsets: list[int] = []
    cursor = 0
    while True:
        found = raw.find(needle, cursor)
        if found < 0:
            break
        offsets.append(found)
        cursor = found + len(needle)

    records: list[dict] = []
    for index, start in enumerate(offsets):
        end = offsets[index + 1] if index + 1 < len(offsets) else len(raw)
        region = raw[start:end]
        code = _read_name_property(region, "CharacterID")
        if not code:
            continue
        gender_raw = (_read_enum_property(region, "Gender") or "").lower()
        gender = "male" if gender_raw == "male" else "female" if gender_raw == "female" else "unknown"
        records.append(
            {
                "id": f"{source}-{index + 1}",
                "code": code,
                "source": source,
                "gender": gender,
                "level": _read_byte_property(region, "Level"),
                "rank": _read_byte_property(region, "Rank"),
                "passives": _read_name_array_property(region, "PassiveSkillList"),
                "talents": {
                    "hp": _read_byte_property(region, "Talent_HP"),
                    "attack": _read_byte_property(region, "Talent_Shot"),
                    "defense": _read_byte_property(region, "Talent_Defense"),
                },
            }
        )
    return records


def load_en_to_key() -> tuple[dict[str, str], dict[str, str]]:
    pals = breeding_data()["pals"]
    english_to_key: dict[str, str] = {}
    chinese: dict[str, str] = {}
    for key, value in pals.items():
        normalized = str(value.get("en", "")).lower().replace(" ", "")
        if normalized:
            english_to_key[normalized] = key
        chinese[key] = str(value.get("zh") or value.get("en") or key)
    return english_to_key, chinese


def _read_str_prop(raw: bytes, key: str) -> str | None:
    key_offset = raw.find(key.encode("ascii") + b"\x00")
    if key_offset < 0:
        return None
    property_offset = raw.find(b"StrProperty\x00", key_offset)
    if property_offset < 0:
        return None
    cursor = property_offset + len(b"StrProperty\x00") + 8 + 1
    if cursor + 4 > len(raw):
        return None
    length = int.from_bytes(raw[cursor : cursor + 4], "little", signed=True)
    cursor += 4
    if length == 0:
        return ""
    if 0 < length <= 4096 and cursor + length <= len(raw):
        return raw[cursor : cursor + length - 1].decode("utf-8", errors="replace")
    if -4096 <= length < 0 and cursor + (-length * 2) <= len(raw):
        return raw[cursor : cursor + (-length * 2) - 2].decode(
            "utf-16-le", errors="replace"
        )
    return None


def _read_int_prop(raw: bytes, key: str) -> int | None:
    key_offset = raw.find(key.encode("ascii") + b"\x00")
    if key_offset < 0:
        return None
    property_offset = raw.find(b"IntProperty\x00", key_offset)
    if property_offset < 0:
        return None
    cursor = property_offset + len(b"IntProperty\x00") + 8 + 1
    if cursor + 4 > len(raw):
        return None
    return int.from_bytes(raw[cursor : cursor + 4], "little", signed=True)


def read_meta(
    world_dir: str | os.PathLike[str],
    dll: str | None = None,
    cancel_event: threading.Event | None = None,
) -> dict:
    world_path = resolved_path(world_dir, strict=False)
    meta_path = world_path / "LevelMeta.sav"
    try:
        stat = meta_path.stat()
    except OSError:
        return {}
    cache = _cache_load()
    meta_cache = cache["meta"]
    cache_key = path_key(world_path)
    cached = meta_cache.get(cache_key)
    if (
        isinstance(cached, dict)
        and cached.get("mtimeNs") == stat.st_mtime_ns
        and cached.get("size") == stat.st_size
    ):
        return {key: cached.get(key) for key in ("world", "host", "day")}
    try:
        raw = decompress_sav(
            meta_path,
            dll if dll is not None else find_oodle_dll(cancel_event),
            cancel_event,
        )
    except OperationCancelled:
        raise
    except Exception:
        return {}
    try:
        stable_stat = meta_path.stat()
    except OSError:
        stable_stat = stat
    info = {
        "world": _read_str_prop(raw, "WorldName"),
        "host": _read_str_prop(raw, "HostPlayerName"),
        "day": _read_int_prop(raw, "InGameDay"),
    }
    with _cache_lock:
        meta_cache[cache_key] = {
            **info,
            "mtimeNs": stable_stat.st_mtime_ns,
            "size": stable_stat.st_size,
        }
        _cache_save()
    return info


def find_global_storage(save_path: str | os.PathLike[str]) -> str | None:
    directory = resolved_path(save_path, strict=False).parent
    for ancestor in (directory, *directory.parents):
        candidate = ancestor / "GlobalPalStorage.sav"
        if candidate.is_file():
            return normalize_path(candidate)
        if ancestor.name.lower() == "savegames":
            break
    return None


def default_save_root() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "Pal" / "Saved" / "SaveGames"
    return Path.home() / "AppData" / "Local" / "Pal" / "Saved" / "SaveGames"


def xbox_wgs_roots() -> list[Path]:
    """返回 Xbox / Game Pass 原生 WGS 容器目录；该格式不是直接的 Level.sav。"""
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        return []
    packages = Path(base) / "Packages"
    if not packages.is_dir():
        return []
    roots: list[Path] = []
    try:
        package_dirs = packages.glob("PocketpairInc.Palworld*")
        for package in package_dirs:
            candidate = package / "SystemAppData" / "wgs"
            if candidate.is_dir():
                roots.append(candidate)
    except OSError:
        return []
    return roots


def default_save_roots() -> list[Path]:
    """快速枚举已知默认位置，不进行耗时的全盘递归扫描。"""
    roots: list[Path] = [default_save_root()]
    configured = os.environ.get("PALWORLD_SAVE_ROOT")
    if configured:
        roots.append(Path(configured))

    for steam_root in _steam_roots():
        roots.extend(
            (
                steam_root / "steamapps" / "common" / "PalServer" / "Pal" / "Saved" / "SaveGames",
                steam_root / "steamapps" / "common" / "Palworld" / "Pal" / "Saved" / "SaveGames",
            )
        )

    base = os.environ.get("LOCALAPPDATA")
    if base:
        packages = Path(base) / "Packages"
        try:
            for package in packages.glob("PocketpairInc.Palworld*"):
                roots.extend(
                    (
                        package / "LocalState" / "Pal" / "Saved" / "SaveGames",
                        package / "LocalCache" / "Local" / "Pal" / "Saved" / "SaveGames",
                    )
                )
        except OSError:
            pass

    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        identity = path_key(root)
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(root)
    return unique


def _make_candidate(
    path: Path, dll: str | None, cancel_event: threading.Event | None = None
) -> dict:
    _check_cancel(cancel_event)
    stat = path.stat()
    world_dir = path.parent
    meta = read_meta(world_dir, dll, cancel_event)
    normalized_parts = {part.lower() for part in path.parts}
    edition = (
        "Xbox 导出"
        if "packages" in normalized_parts
        else "专用服务器"
        if "palserver" in normalized_parts
        else "Steam"
    )
    return {
        "mtime": stat.st_mtime,
        "mtimeNs": stat.st_mtime_ns,
        "size": stat.st_size,
        "path": normalize_path(path),
        "pathKey": path_key(path),
        "account": world_dir.parent.name,
        "guid": world_dir.name,
        "world": meta.get("world"),
        "host": meta.get("host"),
        "day": meta.get("day"),
        "edition": edition,
    }


_SCAN_SKIP_DIRS = {
    "$recycle.bin",
    ".git",
    "backup",
    "cloud",
    "node_modules",
    "recovery",
    "system volume information",
    "windows",
}


def _walk_level_saves(
    root: Path, cancel_event: threading.Event | None = None
) -> Iterable[Path]:
    if not root.is_dir():
        return

    def ignore_error(_: OSError) -> None:
        return None

    for current, directories, files in os.walk(
        root, topdown=True, onerror=ignore_error, followlinks=False
    ):
        _check_cancel(cancel_event)
        directories[:] = [
            name for name in directories if name.lower() not in _SCAN_SKIP_DIRS
        ]
        level_name = next((name for name in files if name.lower() == "level.sav"), None)
        if level_name:
            yield Path(current) / level_name


def _scan_saves_in(
    root: Path,
    dll: str | None,
    candidates: list[dict],
    seen: set[str],
    cancel_event: threading.Event | None = None,
) -> None:
    if not root.is_dir():
        return
    for path in _walk_level_saves(root, cancel_event):
        _check_cancel(cancel_event)
        identity = path_key(path)
        if identity in seen:
            continue
        seen.add(identity)
        try:
            candidates.append(_make_candidate(path, dll, cancel_event))
        except OperationCancelled:
            raise
        except OSError:
            continue


def _remembered_roots() -> list[Path]:
    roots: list[Path] = []
    for root in _cache_load().get("save_roots", []):
        if not isinstance(root, str):
            continue
        path = resolved_path(root, strict=False)
        if path.is_dir():
            roots.append(path)
    return roots


def _infer_save_root(save_path: Path) -> Path:
    directory = save_path.parent
    for ancestor in (directory, *directory.parents):
        if ancestor.name.lower() == "savegames":
            return ancestor
    if directory.parent.parent.is_dir():
        return directory.parent.parent
    return directory


def remember_save_path(save_path: str | os.PathLike[str]) -> None:
    path = resolved_path(save_path, strict=False)
    root = _infer_save_root(path)
    root_text = normalize_path(root)
    identity = path_key(root)
    with _cache_lock:
        roots = _cache_load().setdefault("save_roots", [])
        if all(path_key(item) != identity for item in roots if isinstance(item, str)):
            roots.append(root_text)
            _cache_save()


def _logical_drives() -> list[Path]:
    try:
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        drives: list[Path] = []
        for index, letter in enumerate(string.ascii_uppercase):
            if not bitmask & (1 << index):
                continue
            drive = Path(f"{letter}:\\")
            drive_type = ctypes.windll.kernel32.GetDriveTypeW(str(drive))
            if drive_type in (2, 3):  # removable / fixed
                drives.append(drive)
        return drives
    except Exception:
        return [Path("C:\\")]


def _deep_scan_saves(
    dll: str | None,
    candidates: list[dict],
    seen: set[str],
    progress: Callable[[str], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> None:
    for drive in _logical_drives():
        _check_cancel(cancel_event)
        if progress:
            try:
                progress(str(drive))
            except Exception:
                pass
        _scan_saves_in(drive, dll, candidates, seen, cancel_event)


def list_saves(
    deep: bool = False,
    progress: Callable[[str], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> list[dict]:
    dll = find_oodle_dll(cancel_event)
    candidates: list[dict] = []
    seen: set[str] = set()
    roots = [*default_save_roots(), *_remembered_roots()]
    root_seen: set[str] = set()
    for root in roots:
        _check_cancel(cancel_event)
        identity = path_key(root)
        if identity in root_seen:
            continue
        root_seen.add(identity)
        _scan_saves_in(root, dll, candidates, seen, cancel_event)
    if deep:
        _deep_scan_saves(dll, candidates, seen, progress, cancel_event)
    candidates.sort(key=lambda candidate: candidate["mtimeNs"], reverse=True)
    for candidate in candidates:
        _check_cancel(cancel_event)
        candidate["label"] = format_save_label(candidate)
        if deep and Path(candidate["path"]).is_file():
            try:
                remember_save_path(candidate["path"])
            except OSError:
                pass
    return candidates


def format_save_label(candidate: dict) -> str:
    bits = [time.strftime("%Y-%m-%d %H:%M", time.localtime(candidate["mtime"]))]
    if candidate.get("edition"):
        bits.append(str(candidate["edition"]))
    if candidate.get("world"):
        bits.append(str(candidate["world"]))
    if candidate.get("host"):
        bits.append(f"玩家:{candidate['host']}")
    if candidate.get("day") is not None:
        bits.append(f"第{candidate['day']}天")
    if not candidate.get("world") and not candidate.get("host"):
        bits.append(str(candidate.get("guid", ""))[:8])
    return "  ·  ".join(bits)


def quick_count(
    save_path: str | os.PathLike[str],
    dll: str | None = None,
    cancel_event: threading.Event | None = None,
    storage_cache: dict[str, collections.Counter[str]] | None = None,
) -> int | None:
    try:
        del storage_cache  # 兼容旧调用；快速计数只统计当前世界，不读取跨界基因。
        dll = find_oodle_dll(cancel_event) if dll is None else dll
        raw = decompress_sav(save_path, dll, cancel_event)
        species = extract_species(_world_character_payload(raw))
        _, ignored, _ = _resolve_species(species)
        ignored_count = sum(item["count"] for item in ignored)
        # 未知代码可能是数据刚更新后新增的正式帕鲁，因此仍计入“约 N 只”；
        # 已明确分类的 NPC、联动特殊单位和未发布占位不计入。
        return sum(species.values()) - ignored_count
    except OperationCancelled:
        raise
    except Exception:
        return None


def _heuristic_exclusion(code: str) -> dict | None:
    base = code[5:] if code.lower().startswith("boss_") else code
    lowered = base.lower()
    if lowered in {"", "none"}:
        return {"category": "empty", "reason": "空槽位"}
    if lowered.startswith("yakushima"):
        return {
            "category": "special/terraria",
            "reason": "Terraria 联动特殊单位，不属于常规帕鲁图鉴",
        }
    if lowered == "plantslime_flower":
        return {"category": "special/variant", "reason": "特殊外观单位"}
    if lowered in {"blackfurdragon", "darkmutant"}:
        return {"category": "unreleased/unknown", "reason": "未完成或未发布占位单位"}
    if (
        lowered.startswith(("gym_", "firecult_"))
        or lowered.endswith("_otomo")
    ):
        return {
            "category": "npc/boss-helper",
            "reason": "首领战或阵营运行态随从，不属于玩家帕鲁库存",
        }
    npc_prefixes = (
        "believer_",
        "hunter_",
        "playercharacter",
        "male_",
        "female_",
        "npc_",
        "paldealer",
        "salesperson",
        "merchant",
        "soldier",
        "villager",
    )
    if lowered.startswith(npc_prefixes) or any(
        marker in lowered for marker in ("people", "_guide", "police")
    ):
        return {"category": "npc", "reason": "人类或 NPC 单位"}
    return None


def _resolve_internal_key(code: str, key_mapping: dict[str, str]) -> str | None:
    candidates = [code]
    if code.lower().startswith("boss_"):
        candidates.append(code[5:])
    return next(
        (key_mapping[item.lower()] for item in candidates if item.lower() in key_mapping),
        None,
    )


def _resolve_species(
    species: collections.Counter[str],
    english_to_key: dict[str, str] | None = None,
) -> tuple[dict[str, int], list[dict], list[dict]]:
    del english_to_key  # 兼容旧调用签名；映射在加载 schema 时统一解析。
    key_mapping, excluded_mapping = _load_internal_schema()
    keys: dict[str, int] = {}
    excluded: list[dict] = []
    unknown: list[dict] = []

    for code, count in species.items():
        candidates = [code]
        if code.lower().startswith("boss_"):
            candidates.append(code[5:])

        key = _resolve_internal_key(code, key_mapping)
        if key:
            keys[key] = keys.get(key, 0) + count
            continue

        definition = next(
            (
                excluded_mapping[item.lower()]
                for item in candidates
                if item.lower() in excluded_mapping
            ),
            None,
        )
        if definition is None:
            definition = _heuristic_exclusion(code)
        if definition is not None:
            item = dict(definition)
            item.update({"code": code, "count": count})
            item.setdefault("category", "special")
            item.setdefault("reason", "已知但不参与常规配种")
            excluded.append(item)
        else:
            unknown.append(
                {
                    "code": code,
                    "count": count,
                    "category": "unknownData",
                    "reason": "当前权威数据中没有该内部代号",
                }
            )
    return keys, excluded, unknown


def _merge_records(records: Iterable[dict]) -> list[dict]:
    merged: dict[tuple[str, str], dict] = {}
    for item in records:
        key = (str(item.get("code", "")), str(item.get("category", "")))
        if key not in merged:
            merged[key] = dict(item)
            merged[key]["count"] = int(item.get("count", 0))
        else:
            merged[key]["count"] += int(item.get("count", 0))
    return sorted(merged.values(), key=lambda item: (item["category"], item["code"]))


def _pal_sort_key(value: str) -> tuple[int, str]:
    match = re.match(r"(\d+)(.*)", value)
    if match:
        return int(match.group(1)), match.group(2)
    digits = re.sub(r"\D", "", value)
    return int(digits or 10**9), value


def analyze_save(
    save_path: str | os.PathLike[str],
    log: Callable[[str], None] = print,
    cancel_event: threading.Event | None = None,
) -> dict:
    save = resolved_path(save_path, strict=False)
    if not save.is_file():
        raise RuntimeError("找不到存档 Level.sav。")

    log(f"[存档] {save}")
    dll = find_oodle_dll(cancel_event)
    log(f"[Oodle] {dll or '未找到（仅旧格式可用）'}")

    raw = decompress_sav(save, dll, cancel_event)
    log(f"[解压] Level.sav {len(raw):,} 字节")
    world_payload = _world_character_payload(raw)
    world_species = extract_species(world_payload)
    world_individuals = extract_individuals(world_payload, "world")
    world_species.pop("None", None)

    box_species: collections.Counter[str] = collections.Counter()
    box_individuals: list[dict] = []
    global_storage = find_global_storage(save)
    global_storage_status = "missing"
    global_storage_error = ""
    if global_storage:
        try:
            box_raw = decompress_sav(global_storage, dll, cancel_event)
            box_payload = _global_gene_payload(box_raw)
            box_species = extract_species(box_payload)
            box_individuals = extract_individuals(box_payload, "cross-world")
            box_species.pop("None", None)
            box_individuals = [
                item
                for item in box_individuals
                if str(item.get("code") or "").lower() != "none"
            ]
            global_storage_status = "ok"
        except OperationCancelled:
            raise
        except Exception as exc:
            global_storage_status = "error"
            global_storage_error = str(exc)
            log(f"[跨界基因] 读取失败，已跳过：{exc}")
    else:
        log("[跨界基因] 未找到 GlobalPalStorage.sav")

    world_keys, world_excluded, world_unknown = _resolve_species(world_species)
    box_keys, box_excluded, box_unknown = _resolve_species(box_species)

    _, chinese = load_en_to_key()
    pals = breeding_data()["pals"]
    key_mapping, _ = _load_internal_schema()

    def build_inventory_view(
        counts: dict[str, int], individuals_source: list[dict], source: str
    ) -> list[dict]:
        individuals_by_key: dict[str, list[dict]] = collections.defaultdict(list)
        for individual in individuals_source:
            key = _resolve_internal_key(
                str(individual.get("code", "")), key_mapping
            )
            if key is None:
                continue
            normalized = dict(individual)
            normalized.pop("code", None)
            normalized["key"] = key
            individuals_by_key[key].append(normalized)

        view: list[dict] = []
        for key in sorted(counts, key=_pal_sort_key):
            pal = pals.get(key, {})
            introduced = str(pal.get("introducedIn") or "")
            individuals = individuals_by_key.get(key, [])
            gender_counts = collections.Counter(
                str(item.get("gender") or "unknown") for item in individuals
            )
            count = counts[key]
            view.append(
                {
                    "key": key,
                    "zh": chinese.get(key, key),
                    "count": count,
                    "world": count if source == "save" else 0,
                    "box": count if source == "cross-world" else 0,
                    "source": source,
                    "male": gender_counts.get("male", 0),
                    "female": gender_counts.get("female", 0),
                    "unknownGender": max(
                        gender_counts.get("unknown", 0),
                        count
                        - gender_counts.get("male", 0)
                        - gender_counts.get("female", 0),
                    ),
                    "individuals": individuals,
                    "new": bool(pal.get("new"))
                    or (introduced not in {"", "1.0", "base"})
                    or _pal_sort_key(key)[0] >= 127,
                }
            )
        return view

    owned_view = build_inventory_view(world_keys, world_individuals, "save")
    cross_world_genes = build_inventory_view(
        box_keys, box_individuals, "cross-world"
    )

    meta = read_meta(save.parent, dll, cancel_event)
    source_name = str(meta.get("world") or save.parent.name)
    if meta.get("host"):
        source_name += f"（{meta['host']}）"
    sorted_keys = sorted(world_keys, key=_pal_sort_key)
    sorted_gene_keys = sorted(box_keys, key=_pal_sort_key)
    return {
        "source": source_name,
        "savePath": normalize_path(save),
        "globalStoragePath": global_storage,
        "globalStorageStatus": global_storage_status,
        "globalStorageError": global_storage_error,
        "ownedKeys": sorted_keys,
        "owned": owned_view,
        "crossWorldGeneKeys": sorted_gene_keys,
        "crossWorldGenes": cross_world_genes,
        "excluded": world_excluded,
        "unknownData": world_unknown,
        "crossWorldGeneExcluded": box_excluded,
        "crossWorldGeneUnknownData": box_unknown,
        "skipped": [(item["code"], item["count"]) for item in world_unknown],
        "rawCounts": {
            "world": sum(world_species.values()),
            "box": sum(box_species.values()),
            "individuals": len(world_individuals) + len(box_individuals),
            "ownedWorld": sum(int(item.get("world", 0)) for item in owned_view),
            "ownedBox": sum(
                int(item.get("box", 0)) for item in cross_world_genes
            ),
            "crossWorldGenes": sum(
                int(item.get("count", 0)) for item in cross_world_genes
            ),
            "worldIndividuals": len(world_individuals),
            "crossWorldGeneIndividuals": len(box_individuals),
            "ownedIndividuals": sum(
                len(item.get("individuals", [])) for item in owned_view
            ),
        },
        "dataInfo": data_status(),
    }


def write_json(result: dict, path: str | os.PathLike[str] | None = None) -> str:
    target = Path(path) if path is not None else owned_json_path()
    output = {
        key: result[key]
        for key in (
            "source",
            "savePath",
            "globalStoragePath",
            "globalStorageStatus",
            "globalStorageError",
            "ownedKeys",
            "owned",
            "crossWorldGeneKeys",
            "crossWorldGenes",
            "excluded",
            "unknownData",
            "crossWorldGeneExcluded",
            "crossWorldGeneUnknownData",
            "rawCounts",
            "dataInfo",
        )
        if key in result
    }
    atomic_write_json(target, output, indent=2)
    return normalize_path(target)


def _web_asset_files(source: Path) -> list[Path]:
    top_level_manifest = {"styles.css", "solver.js", "app.js", "palicon.ico"}
    allowed_extensions = {
        ".css",
        ".js",
        ".json",
        ".svg",
        ".ico",
        ".png",
        ".webmanifest",
    }
    top_level_manifest.update(
        item.name
        for item in source.iterdir()
        if item.is_file() and item.suffix.lower() in allowed_extensions
    )
    files = {
        source / name
        for name in top_level_manifest
        if (source / name).is_file()
    }
    for name in ("data", "images"):
        directory = source / name
        if directory.is_dir():
            files.update(item for item in directory.rglob("*") if item.is_file())
    return sorted(files, key=lambda item: item.relative_to(source).as_posix())


def web_asset_fingerprint(source: str | os.PathLike[str] | None = None) -> str:
    root = resolved_path(source, strict=True) if source is not None else asset_dir()
    digest = hashlib.sha256()
    for path in _web_asset_files(root):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _copy_web_assets(
    target_dir: Path, cancel_event: threading.Event | None = None
) -> None:
    source = asset_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    for source_file in _web_asset_files(source):
        _check_cancel(cancel_event)
        target_file = target_dir / source_file.relative_to(source)
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, target_file)


def build_injected_html(
    owned_keys: Iterable[str],
    out_path: str | os.PathLike[str] | None = None,
    cancel_event: threading.Event | None = None,
    *,
    inventory: Iterable[dict] | None = None,
    cross_world_genes: Iterable[dict] | None = None,
    save_meta: dict | None = None,
) -> str:
    target = Path(out_path) if out_path is not None else output_dir() / GENERATED_HTML_NAME
    target = resolved_path(target, strict=False)
    _copy_web_assets(target.parent, cancel_event)
    _check_cancel(cancel_event)
    text = (asset_dir() / "index.html").read_text(encoding="utf-8")
    def script_json(value: object) -> str:
        return (
            json.dumps(value, ensure_ascii=False)
            .replace("&", "\\u0026")
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
        )

    injection_payload = [
        "window.__SAVE_OWNED__=" + script_json(list(owned_keys)),
        "window.__SAVE_INVENTORY__=" + script_json(list(inventory or [])),
        "window.__CROSS_WORLD_GENES__="
        + script_json(list(cross_world_genes or [])),
        "window.__SAVE_META__=" + script_json(save_meta or {}),
    ]
    injection = "<script>" + ";".join(injection_payload) + ";</script>"
    if "</head>" in text:
        text = text.replace("</head>", injection + "\n</head>", 1)
    else:
        text = injection + text
    _atomic_write_text(target, text)
    return normalize_path(target)


def _generated_root() -> Path:
    target = output_dir() / GENERATED_DIR_NAME
    target.mkdir(parents=True, exist_ok=True)
    return target


def _validated_staging_dir(path: str | os.PathLike[str]) -> Path:
    staging = resolved_path(path, strict=False)
    root = resolved_path(_generated_root(), strict=True)
    if staging.parent != root or not staging.name.startswith(".analysis-"):
        raise RuntimeError("生成暂存目录不在受控输出目录中。")
    return staging


def stage_generated_bundle(
    result: dict, cancel_event: threading.Event | None = None
) -> dict:
    root = _generated_root()
    staging = Path(tempfile.mkdtemp(prefix=".analysis-", dir=root))
    try:
        _check_cancel(cancel_event)
        json_path = write_json(result, staging / OWNED_FILE_NAME)
        html_path = build_injected_html(
            result["ownedKeys"],
            staging / GENERATED_HTML_NAME,
            cancel_event,
            inventory=result.get("owned", []),
            cross_world_genes=result.get("crossWorldGenes", []),
            save_meta={
                "source": result.get("source", ""),
                "globalStorageStatus": result.get("globalStorageStatus", "missing"),
                "rawCounts": result.get("rawCounts", {}),
            },
        )
        _check_cancel(cancel_event)
        return {
            "stagingDir": normalize_path(staging),
            "jsonPath": json_path,
            "html": html_path,
        }
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def publish_generated_bundle(staging_dir: str | os.PathLike[str]) -> dict:
    staging = _validated_staging_dir(staging_dir)
    if not staging.is_dir():
        raise RuntimeError("生成暂存目录不存在。")
    suffix = staging.name.removeprefix(".analysis-")
    final = staging.parent / f"run-{suffix}"
    os.replace(staging, final)
    return {
        "runDir": normalize_path(final),
        "jsonPath": normalize_path(final / OWNED_FILE_NAME),
        "html": normalize_path(final / GENERATED_HTML_NAME),
    }


def discard_generated_bundle(staging_dir: str | os.PathLike[str]) -> None:
    try:
        staging = _validated_staging_dir(staging_dir)
    except (OSError, RuntimeError):
        return
    shutil.rmtree(staging, ignore_errors=True)


def cleanup_staged_bundles() -> None:
    root = _generated_root()
    for item in root.glob(".analysis-*"):
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
