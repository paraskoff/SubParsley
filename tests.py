"""Shared fixtures for SubParsley's own tests.

`load_modules_recursive` carries most of this framework's defects and had no
tests at all, because it mutates global interpreter state: it inserts onto
sys.path and populates sys.modules, so a naive test leaks into every test that
runs after it. These two helpers are what make it testable.
"""
import sys
import tempfile
import textwrap
import unittest
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def sandboxed_imports():
    """ Snapshot sys.path and sys.modules, restore them on the way out.

        Without this, importing a fixture module called `schema` would sit in
        sys.modules for the rest of the run and shadow anything else by that
        name — which is exactly the class of bug these tests exist to pin down.
    """
    saved_path = list(sys.path)
    saved_modules = dict(sys.modules)
    try:
        yield
    finally:
        sys.path[:] = saved_path
        for name in set(sys.modules) - set(saved_modules):
            del sys.modules[name]
        sys.modules.update(saved_modules)


class ModuleTreeTestCase(unittest.TestCase):
    """ Base fixture: build a throwaway package tree on disk and load it.

        Subclasses that need more setup should call `super().setUp()` first and
        use `self.tree(...)`.
    """

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def tree(self, spec: dict) -> Path:
        """ Writes `{relative/path.py: source}` under the temp root, creating an
            `__init__.py` in every intermediate package directory so
            load_modules_recursive will actually descend into it.

            Source is dedented, so callers can use readable triple-quoted
            strings indented to match their surrounding code.
        """
        for rel, source in spec.items():
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(source).lstrip("\n"), encoding="utf-8")
            parent = path.parent
            while parent != self.root:
                (parent / "__init__.py").touch()
                parent = parent.parent
        return self.root

    @staticmethod
    def verb(desc: str, ns: str = None, args: dict = None, params: str = "") -> str:
        """Source for one dispatcher function carrying the @ns/@desc/@arg tags."""
        lines = [f"    @desc: {desc}"]
        if ns:
            lines.insert(0, f"    @ns: {ns}")
        for name, help_text in (args or {}).items():
            lines.append(f"    @arg: {name} {help_text}")
        body = "\n".join(lines)
        return f'def run({params}):\n    """\n{body}\n    """\n    return "ran"\n'
