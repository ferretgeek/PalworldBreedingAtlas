from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Callable


CURRENT_VERSION = "3.5.1"


def is_enabled() -> bool:
    """联网下载可执行文件的旧更新通道已永久停用。"""
    return False


def parse_version(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for segment in str(value).strip().lstrip("vV").split("."):
        digits = "".join(character for character in segment if character.isdigit())
        parts.append(int(digits or 0))
    return tuple(parts)


def is_newer(remote: str, local: str) -> bool:
    return parse_version(remote) > parse_version(local)


def check_for_update() -> None:
    """保留兼容入口；程序不会访问网络或执行远程文件。"""
    return None


def download(
    url: str,
    destination: str | os.PathLike[str],
    progress: Callable[[int, int], None] | None = None,
) -> bool:
    """旧版任意 URL 下载能力已移除。"""
    del url, destination, progress
    return False


def update_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    target = (
        Path(base) / "PalBreedHelper" / "update"
        if base
        else Path(tempfile.gettempdir()) / "PalBreedHelper" / "update"
    )
    target.mkdir(parents=True, exist_ok=True)
    return target


def apply_update(new_executable: str | os.PathLike[str]) -> bool:
    """旧版未签名 EXE 自替换能力已移除。"""
    del new_executable
    return False
