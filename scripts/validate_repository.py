#!/usr/bin/env python3
"""Offline repository validation used locally and in CI."""

from __future__ import annotations

import ast
import compileall
import hashlib
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PATHS = [ROOT / "__init__.py", ROOT / "gemini_client.py", ROOT / "nodes", ROOT / "utils"]
EXPECTED_NODES = {
    "GeminiModelGenerator",
    "GeminiVirtualTryOn",
    "GeminiPoseVariation",
    "GeminiGarmentProcessor",
    "GeminiAdvancedRecolor",
    "GeminiStylingAssistant",
    "GeminiOccasionStylist",
}
REQUIRED_FILES = {
    ".gitignore",
    ".comfyignore",
    "README.md",
    "LICENSE",
    "SECURITY.md",
    "PRIVACY.md",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
    "pyproject.toml",
    "requirements.txt",
    "gemini_config.example.json",
    "gemini_client.py",
    "__init__.py",
    "docs/THREAT_MODEL.md",
    "docs/MIGRATION_0.1.0.md",
    ".github/dependabot.yml",
    ".github/pull_request_template.md",
    ".github/workflows/ci.yml",
    ".github/workflows/codeql.yml",
    ".github/workflows/dependency-review.yml",
    ".github/workflows/release.yml",
}
SECRET_PATTERNS = {
    "Google API key": re.compile(r"AIza[0-9A-Za-z_-]{30,}"),
    "OpenAI-style key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b"),
    "Private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}
TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".txt",
    ".json",
    ".toml",
    ".yml",
    ".yaml",
    ".gitignore",
    ".comfyignore",
}


class ValidationError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise ValidationError(message)


def iter_repository_files():
    excluded_parts = {".git", "dist", "build", ".pytest_cache", "__pycache__"}
    for path in sorted(ROOT.rglob("*")):
        if path.is_dir():
            continue
        relative = path.relative_to(ROOT)
        if any(part in excluded_parts for part in relative.parts):
            continue
        yield path, relative



def remove_generated_caches() -> None:
    for cache_dir in sorted(ROOT.rglob("__pycache__"), key=lambda item: len(item.parts), reverse=True):
        if cache_dir.is_dir():
            for child in cache_dir.iterdir():
                if child.is_file() or child.is_symlink():
                    child.unlink()
            cache_dir.rmdir()
    for pyc in ROOT.rglob("*.pyc"):
        pyc.unlink()


def check_structure() -> int:
    present = {str(path.relative_to(ROOT)).replace("\\", "/") for path, _ in iter_repository_files()}
    missing = sorted(REQUIRED_FILES - present)
    if missing:
        fail(f"Missing required files: {', '.join(missing)}")

    forbidden = [
        ROOT / "gemini_config.json",
        ROOT / "gemini_api_key.txt",
        ROOT / "comfyui-fuzhuang2-jingxun.zip",
    ]
    for path in forbidden:
        if path.exists():
            fail(f"Forbidden tracked/runtime artifact exists: {path.name}")

    for path in ROOT.rglob("*"):
        if path.is_symlink():
            fail(f"Symbolic link is not allowed in the release tree: {path.relative_to(ROOT)}")
        if path.suffix == ".pyc" or "__pycache__" in path.parts:
            fail(f"Python cache artifact exists: {path.relative_to(ROOT)}")
        if path.is_file() and path.suffix.lower() == ".zip" and "dist" not in path.parts:
            fail(f"ZIP must be generated under dist/, not tracked: {path.relative_to(ROOT)}")
    return len(present)


def check_text_and_secrets() -> int:
    count = 0
    for path, relative in iter_repository_files():
        if path.name in {".gitignore", ".comfyignore"} or path.suffix.lower() in TEXT_SUFFIXES:
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeError as exc:
                fail(f"Non-UTF-8 text file: {relative}: {exc}")
            for label, pattern in SECRET_PATTERNS.items():
                match = pattern.search(text)
                if match:
                    fail(f"Possible {label} found in {relative} at character {match.start()}")
            count += 1
    return count


def check_example_config() -> None:
    data = json.loads((ROOT / "gemini_config.example.json").read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        fail("gemini_config.example.json must contain an object")
    if data.get("api_key") not in {"", None}:
        fail("gemini_config.example.json must not contain a key")
    if data.get("model") != "gemini-3.1-flash-image":
        fail("Example config model must match the maintained default")


def _runtime_python_files():
    for item in RUNTIME_PATHS:
        if item.is_file():
            yield item
        else:
            yield from sorted(item.glob("*.py"))


def check_runtime_ast() -> int:
    banned_imports = {"subprocess", "pty"}
    banned_calls = {"eval", "exec", "__import__", "os.system", "os.popen"}
    count = 0
    network_importers = []
    for path in _runtime_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        count += 1
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".", 1)[0]
                    if root in banned_imports:
                        fail(f"Banned runtime import '{root}' in {path.relative_to(ROOT)}")
                    if root in {"requests", "httpx", "urllib3"}:
                        network_importers.append(path.relative_to(ROOT))
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".", 1)[0]
                if root in banned_imports:
                    fail(f"Banned runtime import '{root}' in {path.relative_to(ROOT)}")
                if root in {"requests", "httpx", "urllib3"}:
                    network_importers.append(path.relative_to(ROOT))
            elif isinstance(node, ast.Call):
                name = ""
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                    name = f"{node.func.value.id}.{node.func.attr}"
                if name in banned_calls:
                    fail(f"Banned runtime call '{name}' in {path.relative_to(ROOT)}:{node.lineno}")
    unexpected = sorted({str(path) for path in network_importers if str(path) != "gemini_client.py"})
    if unexpected:
        fail(f"Network client imports must stay centralized in gemini_client.py: {unexpected}")
    return count


def check_node_mapping_and_docs() -> None:
    tree = ast.parse((ROOT / "__init__.py").read_text(encoding="utf-8"))
    mapping_keys = set()
    version = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__version__":
                    if isinstance(node.value, ast.Constant):
                        version = node.value.value
                if isinstance(target, ast.Name) and target.id == "NODE_CLASS_MAPPINGS":
                    if not isinstance(node.value, ast.Dict):
                        fail("NODE_CLASS_MAPPINGS must be a literal dictionary")
                    for key in node.value.keys:
                        if isinstance(key, ast.Constant) and isinstance(key.value, str):
                            mapping_keys.add(key.value)
    if mapping_keys != EXPECTED_NODES:
        fail(f"Unexpected node mapping. Expected {sorted(EXPECTED_NODES)}, got {sorted(mapping_keys)}")
    if version != "0.1.0":
        fail(f"Unexpected package version: {version!r}")

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    display_names = {
        "Gemini 模特生成器",
        "Gemini 虚拟试衣",
        "Gemini 姿势变换器",
        "Gemini 服装处理器",
        "Gemini 高级调色盘",
        "Gemini 造型助手",
        "Gemini 场合造型师",
    }
    missing = sorted(name for name in display_names if name not in readme)
    if missing:
        fail(f"README is missing node documentation: {missing}")


def check_workflow_action_pins() -> None:
    """Require immutable full commit SHAs for every third-party GitHub Action."""

    pattern = re.compile(r"^\s*uses:\s*([^#\s]+)")
    sha_ref = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?@[0-9a-fA-F]{40}$")
    for workflow in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        for line_number, line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), 1):
            match = pattern.match(line)
            if not match:
                continue
            action = match.group(1)
            if action.startswith("./"):
                continue
            if not sha_ref.fullmatch(action):
                fail(
                    f"GitHub Action must be pinned to a 40-character commit SHA: "
                    f"{workflow.relative_to(ROOT)}:{line_number}: {action}"
                )


def check_dependencies() -> None:
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    if "google-generativeai" in requirements.lower():
        fail("Unused legacy google-generativeai dependency must not return")
    required = {"requests", "pillow", "numpy"}
    found = {
        re.split(r"[<>=!~\[]", line.strip().lower(), maxsplit=1)[0]
        for line in requirements.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    if found != required:
        fail(f"Unexpected direct dependency set: {sorted(found)}")


def repository_digest() -> str:
    hasher = hashlib.sha256()
    for path, relative in iter_repository_files():
        rel = str(relative).replace("\\", "/").encode("utf-8")
        data = path.read_bytes()
        hasher.update(len(rel).to_bytes(4, "big"))
        hasher.update(rel)
        hasher.update(len(data).to_bytes(8, "big"))
        hasher.update(data)
    return hasher.hexdigest()


def main() -> int:
    try:
        remove_generated_caches()
        file_count = check_structure()
        text_count = check_text_and_secrets()
        check_example_config()
        runtime_count = check_runtime_ast()
        check_node_mapping_and_docs()
        check_dependencies()
        check_workflow_action_pins()
        if not compileall.compile_dir(ROOT, quiet=1, force=True):
            fail("Python compilation failed")
        # compileall creates caches; remove them so validation leaves the tree clean.
        for cache_dir in sorted(ROOT.rglob("__pycache__"), reverse=True):
            for child in cache_dir.iterdir():
                child.unlink()
            cache_dir.rmdir()
        print(
            "Repository validation passed: "
            f"{file_count} files, {text_count} UTF-8 text files, "
            f"{runtime_count} runtime Python files."
        )
        print(f"Repository digest: {repository_digest()}")
        return 0
    except (ValidationError, OSError, ValueError, SyntaxError, json.JSONDecodeError) as exc:
        print(f"Repository validation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
