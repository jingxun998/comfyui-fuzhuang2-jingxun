#!/usr/bin/env python3
"""Build a deterministic manual-install ZIP from the validated source tree."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
PROJECT_FOLDER = "comfyui-fuzhuang2-jingxun"
EXCLUDED_PARTS = {".git", ".github", "tests", "scripts", "dist", "build", "__pycache__", ".pytest_cache"}
EXCLUDED_NAMES = {"gemini_config.json", "gemini_api_key.txt", ".DS_Store"}


def package_version() -> str:
    text = (ROOT / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, flags=re.MULTILINE)
    if not match:
        raise RuntimeError("Could not read __version__")
    return match.group(1)


def source_files():
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(ROOT)
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        if path.name in EXCLUDED_NAMES or path.suffix == ".pyc":
            continue
        yield path, relative


def add_bytes(archive: zipfile.ZipFile, arcname: str, data: bytes) -> None:
    info = zipfile.ZipInfo(arcname, date_time=(2026, 8, 11, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, data, compresslevel=9)


def build(version: str) -> tuple[Path, Path]:
    if version != package_version():
        raise RuntimeError(
            f"Requested version {version!r} does not match package version {package_version()!r}."
        )
    subprocess.run([sys.executable, str(ROOT / "scripts" / "validate_repository.py")], check=True)
    DIST.mkdir(exist_ok=True)
    zip_path = DIST / f"{PROJECT_FOLDER}-v{version}.zip"
    checksum_path = DIST / f"{zip_path.name}.sha256"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w") as archive:
        for path, relative in source_files():
            arcname = f"{PROJECT_FOLDER}/{str(relative).replace(os.sep, '/')}"
            add_bytes(archive, arcname, path.read_bytes())
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    checksum_path.write_text(f"{digest}  {zip_path.name}\n", encoding="utf-8")
    print(zip_path)
    print(checksum_path)
    print(f"SHA256 {digest}")
    return zip_path, checksum_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default=package_version())
    args = parser.parse_args()
    build(args.version.lstrip("v"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
