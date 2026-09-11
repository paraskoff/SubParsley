"""Tests for load_modules_recursive: ignore patterns, sys.path, import errors."""
import os
import sys
import unittest
from unittest.mock import patch

import SubParsley as sp
from tests import ModuleTreeTestCase, sandboxed_imports


class LoaderTestCase(ModuleTreeTestCase):
    def load(self, **kwargs):
        with sandboxed_imports():
            return sp.load_modules_recursive(self.root, **kwargs)

    def names(self, **kwargs):
        return [name for name, _mod in self.load(**kwargs)]


class IgnorePatternTests(LoaderTestCase):
    """Testing that test modules are not imported on every CLI invocation.

    In kolobar this is 55 of 122 .py files — 45% of every import, plus unittest
    itself, before argparse is even constructed.
    """

    def setUp(self):
        super().setUp()
        self.tree({
            "cmd.py": "X = 1\n",
            "cmd_tests.py": "X = 1\n",
            "cmd_test.py": "X = 1\n",
            "tests.py": "X = 1\n",
            "conftest.py": "X = 1\n",
            "manifest.py": "X = 1\n",
            "latest.py": "X = 1\n",
        })

    def test__real_modules_are_loaded(self):
        """Verify ordinary dispatchers still load."""
        self.assertIn("cmd", self.names())

    def test__test_modules_are_skipped(self):
        """Verify *_test*.py contributes nothing and costs nothing."""
        loaded = self.names()
        self.assertNotIn("cmd_tests", loaded)
        self.assertNotIn("cmd_test", loaded)

    def test__shared_test_helpers_are_skipped(self):
        """Verify tests.py and conftest.py are skipped too."""
        loaded = self.names()
        self.assertNotIn("tests", loaded)
        self.assertNotIn("conftest", loaded)

    def test__dunder_main_is_skipped(self):
        """Verify __main__.py is never imported. import_module("__main__") returns
        the already-running entry module — SubParsley itself — whose docstrings
        mention `@desc:` and `@ns:` while documenting them, so it registers its own
        internals as verbs. A consumer hit this by adding a console-script entry
        point inside its package."""
        self.tree({"__main__.py": "X = 1\n"})
        self.assertNotIn("__main__", self.names())

    def test__a_consumer_entry_point_does_not_publish_framework_internals(self):
        """Verify the end-to-end symptom is gone: no noun named __main__, and none
        of SubParsley's own function docstrings become commands."""
        self.tree({
            "__main__.py": "def main():\n    return 0\n",
            "real.py": self.verb("A real command", ns="real"),
        })
        with sandboxed_imports():
            parser = sp.setup_cli(self.root)
        nouns = set(parser._subparsers._group_actions[0].choices)
        self.assertEqual(nouns, {"real"})

    def test__innocent_names_are_not_caught(self):
        """Verify `*_test*.py` does not over-match. `manifest.py` and `latest.py`
        both contain the substring 'test' and must still load."""
        loaded = self.names()
        self.assertIn("manifest", loaded)
        self.assertIn("latest", loaded)

    def test__project_ignore_is_additive(self):
        """Verify a custom pattern adds to the defaults rather than replacing them."""
        with patch.dict(os.environ, {sp.IGNORE_ENV_VAR: "manifest.py"}):
            loaded = self.names(ignore=sp.resolve_ignore_patterns())
        self.assertNotIn("manifest", loaded)
        self.assertNotIn("cmd_tests", loaded, "defaults must survive a custom pattern")

    def test__defaults_can_be_dropped_explicitly(self):
        """Verify opting out is possible but requires its own variable — an accidental
        override would silently reintroduce the defect and cost only latency, so it
        would never be noticed."""
        with patch.dict(os.environ, {sp.IGNORE_DEFAULTS_ENV_VAR: "0"}):
            loaded = self.names(ignore=sp.resolve_ignore_patterns())
        self.assertIn("cmd_tests", loaded)

    def test__ignored_modules_contribute_no_verbs(self):
        """Verify skipping happens before verb collection, not after."""
        self.tree({"skipme_tests.py": self.verb("Should never appear", ns="ghost")})
        parser = None
        with sandboxed_imports():
            parser = sp.setup_cli(self.root)
        nouns = parser._subparsers._group_actions[0].choices
        self.assertNotIn("ghost", nouns)


class SubdirectoryIgnoreTests(LoaderTestCase):
    """Testing that ignore patterns prune whole subtrees"""

    def test__a_relative_path_pattern_prunes_a_directory(self):
        """Verify PROJECT_IGNORE can exclude a subtree, not just filenames."""
        self.tree({"keep/a.py": "X = 1\n", "drop/b.py": "X = 1\n"})
        loaded = self.names(ignore=("drop",))
        self.assertIn("keep.a", loaded)
        self.assertNotIn("drop.b", loaded)


class SysPathTests(LoaderTestCase):
    """Testing that only the project root goes on sys.path"""

    def test__exactly_one_entry_is_added(self):
        """Verify the root is inserted once and no subdirectory is."""
        self.tree({"a.py": "X = 1\n", "pkg/b.py": "X = 1\n", "pkg/deep/c.py": "X = 1\n"})
        before = list(sys.path)
        with sandboxed_imports():
            sp.load_modules_recursive(self.root)
            added = [p for p in sys.path if p not in before]
        self.assertEqual(added, [str(self.root)])

    def test__nested_modules_get_correct_dotted_names(self):
        """Verify the dotted-name construction works at three levels deep."""
        self.tree({"pkg/deep/c.py": "X = 1\n"})
        self.assertIn("pkg.deep.c", self.names())

    def test__same_named_modules_at_different_depths_both_load(self):
        """Verify shadowing is impossible. kolobar has schema.py at five levels; it
        worked only because root modules happened to import first and win the
        sys.modules cache — a load-order accident, not a design."""
        self.tree({
            "schema.py": "WHO = 'root'\n",
            "models/schema.py": "WHO = 'models'\n",
            "services/schema.py": "WHO = 'services'\n",
        })
        loaded = dict(self.load())
        self.assertEqual(loaded["schema"].WHO, "root")
        self.assertEqual(loaded["models.schema"].WHO, "models")
        self.assertEqual(loaded["services.schema"].WHO, "services")

    def test__a_module_wins_over_a_same_named_data_directory(self):
        """Verify schema.py beats a sibling schema/ with no __init__.py. A directory
        without __init__.py is only a namespace-package fallback, so the file wins —
        pinned because kolobar relies on it."""
        self.tree({"schema.py": "WHO = 'file'\n"})
        (self.root / "schema").mkdir()
        (self.root / "schema" / "data.json").write_text("{}", encoding="utf-8")
        loaded = dict(self.load())
        self.assertEqual(loaded["schema"].WHO, "file")

    def test__a_directory_without_init_is_not_descended_into(self):
        """Verify documented behaviour: no __init__.py means not a package."""
        self.tree({"a.py": "X = 1\n"})
        plain = self.root / "plain"
        plain.mkdir()
        (plain / "b.py").write_text("X = 1\n", encoding="utf-8")
        self.assertNotIn("plain.b", self.names())

    def test__underscore_directories_are_skipped(self):
        """Verify _private/ and __pycache__/ are never descended into."""
        self.tree({"a.py": "X = 1\n", "_private/b.py": "X = 1\n"})
        self.assertNotIn("_private.b", self.names())


class ImportFailureTests(LoaderTestCase):
    """Testing that a broken module is reported, not silently dropped"""

    def test__a_broken_module_is_skipped_and_others_still_load(self):
        """Verify one bad dispatcher does not take down the CLI."""
        self.tree({"good.py": "X = 1\n", "bad.py": "def (\n"})
        collected = []
        loaded = self.names(on_error=lambda n, e: collected.append(n))
        self.assertIn("good", loaded)
        self.assertNotIn("bad", loaded)
        self.assertEqual(collected, ["bad"])

    def test__on_error_receives_the_module_name_and_exception(self):
        """Verify the hook gets enough to report or to fail a CI build."""
        self.tree({"bad.py": "def (\n"})
        seen = []
        self.load(on_error=lambda n, e: seen.append((n, e)))
        self.assertEqual(seen[0][0], "bad")
        self.assertIsInstance(seen[0][1], SyntaxError)

    def test__the_default_warning_names_the_module_and_goes_to_stderr(self):
        """Verify the replacement for the old bare `print(e)`: a stray unlabelled
        line was the only clue that a whole namespace had vanished."""
        import io
        from contextlib import redirect_stderr, redirect_stdout
        self.tree({"bad.py": "def (\n"})
        out, err = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {}, clear=True):
            with redirect_stdout(out), redirect_stderr(err):
                self.load()
        self.assertIn("bad", err.getvalue())
        self.assertIn("SyntaxError", err.getvalue())
        self.assertEqual(out.getvalue(), "")

    def test__debug_re_raises(self):
        """Verify a broken module is a hard failure when diagnosing."""
        self.tree({"bad.py": "def (\n"})
        with patch.dict(os.environ, {sp.DEBUG_ENV_VAR: "1"}):
            with self.assertRaises(SyntaxError):
                self.load(on_error=lambda n, e: None)

    def test__system_exit_at_import_time_is_not_swallowed(self):
        """Verify `except Exception` is narrow enough: a module calling sys.exit() at
        import used to be absorbed into a stray print."""
        self.tree({"exiter.py": "import sys\nsys.exit(3)\n"})
        with self.assertRaises(SystemExit):
            self.load(on_error=lambda n, e: None)


class PackageLoaderTests(LoaderTestCase):
    """Testing PROJECT_PACKAGE: importing by package name, not by directory.

    The directory path has to put PROJECT_DIR on sys.path, which for an
    INSTALLED consumer means inserting its own package directory and making its
    subpackages importable as bare top-level names — exactly the flat namespace
    that packaging it was meant to escape.
    """

    def install(self, spec):
        """Build a package under the temp root and make it importable."""
        self.tree({f"mypkg/{rel}": src for rel, src in spec.items()})
        (self.root / "mypkg" / "__init__.py").touch()
        return self.root

    def test__submodules_are_imported_by_their_real_dotted_names(self):
        """Verify names are `mypkg.thing`, not the bare `thing` the directory
        scanner would produce."""
        root = self.install({"thing.py": "X = 1\n", "sub/deep.py": "X = 2\n"})
        with sandboxed_imports():
            sys.path.insert(0, str(root))
            names = [n for n, _m in sp.load_package_modules("mypkg")]
        self.assertIn("mypkg.thing", names)
        self.assertIn("mypkg.sub.deep", names)
        self.assertNotIn("thing", names)

    def test__sys_path_is_not_touched(self):
        """Verify the whole point: no directory is inserted, so no bare name
        becomes importable as a side effect."""
        root = self.install({"thing.py": "X = 1\n"})
        with sandboxed_imports():
            sys.path.insert(0, str(root))
            before = list(sys.path)
            sp.load_package_modules("mypkg")
            self.assertEqual(sys.path, before)

    def test__it_builds_the_same_cli_as_directory_scanning(self):
        """Verify the two loaders agree on the resulting command surface."""
        root = self.install({"cmd.py": self.verb("Do a thing", ns="demo")})
        with sandboxed_imports():
            sys.path.insert(0, str(root))
            parser = sp.setup_cli_from_package("mypkg")
        self.assertIn("demo", parser._subparsers._group_actions[0].choices)

    def test__ignore_patterns_apply_here_too(self):
        """Verify test modules are skipped on this path as well."""
        root = self.install({"cmd.py": "X = 1\n", "cmd_tests.py": "X = 1\n"})
        with sandboxed_imports():
            sys.path.insert(0, str(root))
            names = [n for n, _m in sp.load_package_modules("mypkg")]
        self.assertIn("mypkg.cmd", names)
        self.assertNotIn("mypkg.cmd_tests", names)

    def test__an_unimportable_package_fails_with_a_clear_message(self):
        """Verify a typo'd PROJECT_PACKAGE says so, rather than yielding an empty CLI."""
        import io
        from contextlib import redirect_stderr
        err = io.StringIO()
        with patch.dict(os.environ, {}, clear=True):
            with redirect_stderr(err):
                with self.assertRaises(SystemExit):
                    sp.load_package_modules("no_such_package_xyz")
        self.assertIn("PROJECT_PACKAGE", err.getvalue())

    def test__a_broken_submodule_is_reported_not_fatal(self):
        """Verify the same degradation as the directory scanner."""
        root = self.install({"good.py": "X = 1\n", "bad.py": "def (\n"})
        seen = []
        with sandboxed_imports():
            sys.path.insert(0, str(root))
            names = [n for n, _m in sp.load_package_modules(
                "mypkg", on_error=lambda n, e: seen.append(n))]
        self.assertIn("mypkg.good", names)
        self.assertEqual(seen, ["mypkg.bad"])


if __name__ == "__main__":
    unittest.main()
