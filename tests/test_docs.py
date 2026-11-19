import ast
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*parts):
    with open(os.path.join(ROOT, *parts)) as f:
        return f.read()


def _handlers():
    """Public handlers in shop/api.py, and which of them call auth.allowed."""
    tree = ast.parse(_read("shop", "api.py"))
    public, gated = [], []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
            public.append(node.name)
            for call in ast.walk(node):
                if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                        and call.func.attr == "allowed"
                        and isinstance(call.func.value, ast.Name) and call.func.value.id == "auth"):
                    gated.append(node.name)
                    break
    return public, gated


def test_every_public_handler_is_documented():
    docs = _read("docs", "api.md")
    public, _ = _handlers()
    assert public
    missing = [n for n in public if f"`api.{n}`" not in docs]
    assert not missing, missing


def test_gated_handlers_are_listed_as_gated():
    docs = _read("docs", "api.md")
    _, gated = _handlers()
    assert gated
    section = re.search(r"## Who may call\n(.*?)(?=\n## )", docs, re.DOTALL).group(1)
    missing = [n for n in gated if f"`api.{n}`" not in section]
    assert not missing, missing
    assert "only `api.delete_product`" not in docs
