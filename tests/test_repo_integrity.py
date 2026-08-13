"""Whole-repo checks that no unit test would catch.

The interface is HTML plus a canvas plus hand-written DOM updates, so nothing verifies
that the two halves still agree — rename an element and the page silently half-works.
These are the cheap structural guarantees that make that impossible.
"""

from __future__ import annotations

import ast
import html.parser
import importlib
import pkgutil
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

import emgdemo

REPO = Path(__file__).resolve().parent.parent
PACKAGE = Path(emgdemo.__file__).parent
UI = PACKAGE / "ui"

SKIP_DIRS = {"legacy", ".venv", "__pycache__", ".git", "node_modules", "EMGdataset"}

#: Modules the engine must never pull in at import time. The core has to stay runnable
#: with no screen and no hardware attached, which is what lets it be tested at all.
FORBIDDEN_IN_CORE = {"matplotlib", "serial", "bleak", "tkinter", "PyQt5", "PySide6"}

VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "source",
    "track",
    "wbr",
}


def _repo_files(pattern: str) -> list[Path]:
    return [
        path
        for path in sorted(REPO.rglob(pattern))
        if not any(part in SKIP_DIRS for part in path.relative_to(REPO).parts)
    ]


def _package_modules() -> list[str]:
    return [emgdemo.__name__] + [
        name for _, name, _ in pkgutil.walk_packages(emgdemo.__path__, prefix="emgdemo.")
    ]


class _Markup(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.open_tags: list[str] = []
        self.ids: list[str] = []
        self.problems: list[str] = []

    def handle_starttag(self, tag, attrs):
        self.ids.extend(value for key, value in attrs if key == "id" and value)
        if tag not in VOID_TAGS:
            self.open_tags.append(tag)

    def handle_endtag(self, tag):
        if tag in VOID_TAGS:
            return
        if not self.open_tags:
            self.problems.append(f"stray </{tag}>")
        elif self.open_tags[-1] != tag:
            self.problems.append(f"</{tag}> closes <{self.open_tags[-1]}>")
            self.open_tags.pop()
        else:
            self.open_tags.pop()


def _markup(path: Path) -> _Markup:
    parser = _Markup()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser


# ---- source files parse ----------------------------------------------------


@pytest.mark.parametrize("path", _repo_files("*.py"), ids=lambda p: p.name)
def test_python_files_parse(path: Path):
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


@pytest.mark.parametrize("name", _package_modules())
def test_every_module_imports(name: str):
    importlib.import_module(name)


@pytest.mark.parametrize("path", _repo_files("*.toml"), ids=lambda p: p.name)
def test_toml_files_parse(path: Path):
    tomllib.loads(path.read_text(encoding="utf-8"))


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@pytest.mark.parametrize("path", _repo_files("*.js"), ids=lambda p: p.name)
def test_javascript_parses(path: Path):
    result = subprocess.run(
        ["node", "--check", str(path)], capture_output=True, text=True, shell=True
    )
    assert result.returncode == 0, result.stderr.strip()


# ---- the interface holds together ------------------------------------------


@pytest.mark.parametrize("path", _repo_files("*.html"), ids=lambda p: p.name)
def test_markup_is_well_formed(path: Path):
    parsed = _markup(path)
    assert not parsed.problems, parsed.problems
    assert not parsed.open_tags, f"unclosed: {parsed.open_tags}"


@pytest.mark.parametrize("path", _repo_files("*.html"), ids=lambda p: p.name)
def test_element_ids_are_unique(path: Path):
    ids = _markup(path).ids
    duplicates = sorted({name for name in ids if ids.count(name) > 1})
    assert not duplicates, duplicates


def test_every_id_the_script_reaches_for_exists_in_the_markup():
    markup_ids = {name for path in _repo_files("*.html") for name in _markup(path).ids}
    referenced = set()
    for path in _repo_files("*.js"):
        referenced |= set(
            re.findall(
                r"""(?:getElementById|\bel|\bsetText)\(\s*["']([^"']+)["']""",
                path.read_text(encoding="utf-8"),
            )
        )

    assert referenced, "found no element references - the pattern has stopped matching"
    assert not referenced - markup_ids, sorted(referenced - markup_ids)


@pytest.mark.parametrize("path", _repo_files("*.css"), ids=lambda p: p.name)
def test_stylesheet_braces_balance(path: Path):
    text = path.read_text(encoding="utf-8")
    assert text.count("{") == text.count("}")


def test_the_page_loads_only_assets_that_ship():
    referenced = set(
        re.findall(r'(?:src|href)="/([^"]+)"', (UI / "index.html").read_text(encoding="utf-8"))
    )
    missing = sorted(name for name in referenced if not (UI / name).is_file())
    assert not missing, missing


# ---- architecture ----------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [p for p in _repo_files("*.py") if PACKAGE in p.parents],
    ids=lambda p: p.name,
)
def test_the_core_imports_no_ui_or_hardware_at_module_level(path: Path):
    """Hardware and UI libraries may be imported inside functions, never at the top.

    That is what keeps `pip install emgdemo` working without pyserial or bleak, and the
    engine testable with no screen attached.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    offenders = []
    for node in tree.body:  # module level only
        if isinstance(node, ast.Import):
            offenders += [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            offenders.append(node.module.split(".")[0])

    assert not (set(offenders) & FORBIDDEN_IN_CORE), sorted(set(offenders) & FORBIDDEN_IN_CORE)
