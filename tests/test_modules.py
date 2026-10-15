"""
Jedes Modul muss sich laden lassen

Ein Syntaxfehler in einem Cog fällt sonst erst auf, wenn der Bot startet.
"""

import importlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MODULES = ["bot", "database", "migrations"] + sorted(
    f"{package}.{path.stem}"
    for package in ("cogs", "services")
    for path in (ROOT / package).glob("*.py")
    if path.stem != "__init__"
)


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name):
    importlib.import_module(name)


def test_every_cog_is_loaded_by_the_bot():
    source = (ROOT / "bot.py").read_text()
    for path in (ROOT / "cogs").glob("*.py"):
        if path.stem != "__init__":
            assert f'load_extension("cogs.{path.stem}")' in source, path.stem


def test_level_text_names_the_next_rank():
    from cogs.profiles import _get_level, _get_next_level

    assert _get_level(0)[0] == "Gascogner"
    assert _get_level(3)[0] == "Buchketier"
    assert _get_next_level(0) == ("Gardist bei des Essarts", 1)
    assert _get_next_level(20) is None
