from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "fuzhuang_test_package"


@pytest.fixture(scope="session")
def plugin():
    spec = importlib.util.spec_from_file_location(
        PACKAGE_NAME,
        ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load plugin package")
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE_NAME] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def clean_gemini_environment(monkeypatch):
    prefixes = ("GEMINI_", "GOOGLE_API_")
    exact = {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"}
    for name in list(__import__("os").environ):
        if name.startswith(prefixes) or name in exact:
            monkeypatch.delenv(name, raising=False)
