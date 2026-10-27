import copy
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
EXAMPLES = os.path.join(ROOT, "examples")

BOARD = {"id": "b20", "kind": "board", "name": "Board", "thickness": 20, "width": 200, "length": 2000}


def model(parts, steps=None, **extra):
    """Минимальная модель: по шагу на каждую деталь, если шаги не заданы."""
    m = {
        "title": "Test",
        "stock": [copy.deepcopy(BOARD)],
        "parts": parts,
        "steps": steps if steps is not None else [{"title": p["id"], "add": [p["id"]]} for p in parts],
    }
    m.update(extra)
    return m


def box(pid, origin, size, **kw):
    d = {"id": pid, "name": pid, "stock": "b20", "origin": list(origin), "size": list(size)}
    d.update(kw)
    return d


def codes(issues, level=None):
    return [i.code for i in issues if level is None or i.level == level]


@pytest.fixture
def example_path():
    return lambda name: os.path.join(EXAMPLES, name)
