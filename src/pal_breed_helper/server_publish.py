from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Sequence

from . import save_parser
from .updater import CURRENT_VERSION


STATUS_SCHEMA = "pal-breed-helper-server-v1"
STATUS_FILE_NAME = "server-status.json"
SERVER_HTML_NAME = "index.html"


def _utc_iso(timestamp: float | None = None) -> str:
    value = time.time() if timestamp is None else timestamp
    return dt.datetime.fromtimestamp(value, dt.timezone.utc).isoformat(timespec="seconds")


def save_signature(path: str | os.PathLike[str]) -> dict[str, Any]:
    target = save_parser.resolved_path(path, strict=True)
    stat = target.stat()
    return {
        "key": f"{stat.st_mtime_ns}:{stat.st_size}",
        "mtimeNs": stat.st_mtime_ns,
        "mtime": stat.st_mtime,
        "modifiedAt": _utc_iso(stat.st_mtime),
        "size": stat.st_size,
    }


def _load_status(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _public_result(result: dict[str, Any]) -> dict[str, Any]:
    public = dict(result)
    public["savePath"] = "Level.sav"
    if public.get("globalStoragePath"):
        public["globalStoragePath"] = "GlobalPalStorage.sav"
    return public


def _public_error(exc: BaseException) -> str:
    return f"{type(exc).__name__}: 存档解析或静态发布失败；详细原因仅保留在本机受控日志。"


def publish_latest(
    save_path: str | os.PathLike[str],
    output_dir: str | os.PathLike[str],
    *,
    force: bool = False,
    log=print,
) -> dict[str, Any]:
    started_monotonic = time.monotonic()
    save = save_parser.resolved_path(save_path, strict=True)
    if not save.is_file():
        raise RuntimeError(f"找不到服务器存档：{save}")
    output = save_parser.resolved_path(output_dir, strict=False)
    output.mkdir(parents=True, exist_ok=True)
    status_path = output / STATUS_FILE_NAME
    previous = _load_status(status_path)
    source = save_signature(save)
    published_key = str(previous.get("publishedSignature") or "")
    html_path = output / SERVER_HTML_NAME
    if not force and published_key == source["key"] and html_path.is_file():
        result = dict(previous)
        result.update(
            {
                "schema": STATUS_SCHEMA,
                "busy": False,
                "changed": False,
                "fresh": True,
                "sourceSignature": source["key"],
                "sourceModifiedAt": source["modifiedAt"],
                "sourceSize": source["size"],
                "lastError": "",
            }
        )
        save_parser.atomic_write_json(status_path, result, indent=2)
        return result

    pending = dict(previous)
    pending.update(
        {
            "schema": STATUS_SCHEMA,
            "assistantVersion": CURRENT_VERSION,
            "busy": True,
            "changed": False,
            "fresh": False,
            "sourceSignature": source["key"],
            "sourceModifiedAt": source["modifiedAt"],
            "sourceSize": source["size"],
            "startedAt": _utc_iso(),
            "lastError": "",
        }
    )
    save_parser.atomic_write_json(status_path, pending, indent=2)

    try:
        result = save_parser.analyze_save(save, log)
        analyzed_at = _utc_iso()
        public = _public_result(result)
        meta = {
            "deployment": "server",
            "assistantVersion": CURRENT_VERSION,
            "source": result.get("source", "服务器最新存档"),
            "saveModifiedAt": source["modifiedAt"],
            "analyzedAt": analyzed_at,
            "signature": source["key"],
            "globalStorageStatus": result.get("globalStorageStatus", "missing"),
            "rawCounts": result.get("rawCounts", {}),
        }
        save_parser.write_json(public, output / save_parser.OWNED_FILE_NAME)
        save_parser.build_injected_html(
            result.get("ownedKeys", []),
            html_path,
            inventory=result.get("owned", []),
            cross_world_genes=result.get("crossWorldGenes", []),
            save_meta=meta,
        )
        current_source = save_signature(save)
        counts = result.get("rawCounts", {})
        finished = {
            "schema": STATUS_SCHEMA,
            "assistantVersion": CURRENT_VERSION,
            "busy": False,
            "changed": True,
            "fresh": current_source["key"] == source["key"],
            "sourceSignature": current_source["key"],
            "sourceModifiedAt": current_source["modifiedAt"],
            "sourceSize": current_source["size"],
            "publishedSignature": source["key"],
            "publishedSaveModifiedAt": source["modifiedAt"],
            "analyzedAt": analyzed_at,
            "durationSeconds": round(time.monotonic() - started_monotonic, 3),
            "sourceLabel": str(result.get("source") or "服务器最新存档"),
            "speciesCount": len(result.get("ownedKeys", [])),
            "palCount": int(counts.get("ownedWorld") or 0),
            "crossWorldGeneCount": int(counts.get("crossWorldGenes") or 0),
            "globalStorageStatus": str(result.get("globalStorageStatus") or "missing"),
            "lastError": "",
        }
        save_parser.atomic_write_json(status_path, finished, indent=2)
        return finished
    except BaseException as exc:
        log(f"发布失败（{type(exc).__name__}）")
        failed = dict(previous)
        failed.update(
            {
                "schema": STATUS_SCHEMA,
                "assistantVersion": CURRENT_VERSION,
                "busy": False,
                "changed": False,
                "fresh": False,
                "sourceSignature": source["key"],
                "sourceModifiedAt": source["modifiedAt"],
                "sourceSize": source["size"],
                "failedAt": _utc_iso(),
                "lastError": _public_error(exc),
            }
        )
        save_parser.atomic_write_json(status_path, failed, indent=2)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="只读解析服务器最新 Level.sav 并发布浏览器配种助手")
    parser.add_argument("--save", required=True, help="Level.sav 的绝对路径")
    parser.add_argument("--output", required=True, help="受保护网页目录")
    parser.add_argument("--force", action="store_true", help="即使存档未变化也重新解析")
    args = parser.parse_args(argv)
    result = publish_latest(args.save, args.output, force=args.force)
    print(
        json.dumps(
            {
                "ok": True,
                "changed": bool(result.get("changed")),
                "fresh": bool(result.get("fresh")),
                "speciesCount": int(result.get("speciesCount") or 0),
                "palCount": int(result.get("palCount") or 0),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
