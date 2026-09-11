"""Tests for main(), fail() and the debug switch."""
import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import SubParsley as sp
from tests import ModuleTreeTestCase


class DebugEnabledTests(unittest.TestCase):
    """Testing debug_enabled"""

    def test__unset_is_off(self):
        """Verify the default is quiet."""
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(sp.debug_enabled())

    def test__set_is_on(self):
        """Verify any ordinary value turns it on."""
        with patch.dict(os.environ, {sp.DEBUG_ENV_VAR: "1"}):
            self.assertTrue(sp.debug_enabled())

    def test__zero_is_off(self):
        """Verify SUBPARSLEY_DEBUG=0 means off. A bare truthiness check on the
        string would turn it ON, which is the opposite of what a human intends."""
        for value in ("0", "false", "no", ""):
            with patch.dict(os.environ, {sp.DEBUG_ENV_VAR: value}):
                self.assertFalse(sp.debug_enabled(), value)


class FailTests(unittest.TestCase):
    """Testing fail()"""

    def run_fail(self, *args, **kwargs):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            with self.assertRaises(SystemExit) as cm:
                sp.fail(*args, **kwargs)
        return out.getvalue(), err.getvalue(), cm.exception.code

    def test__message_goes_to_stderr_not_stdout(self):
        """Verify diagnostics leave stdout clean. Errors used to print to stdout, so
        `SBOR=$(klbr sbor show --brief)` captured error text as data."""
        with patch.dict(os.environ, {}, clear=True):
            out, err, _ = self.run_fail("boom")
        self.assertEqual(out, "")
        self.assertIn("Error: boom", err)

    def test__exit_code_is_one(self):
        """Verify the exit code is unchanged — scripts branch on it."""
        with patch.dict(os.environ, {}, clear=True):
            _out, _err, code = self.run_fail("boom")
        self.assertEqual(code, 1)

    def test__prefix_is_unchanged(self):
        """Verify the `Error: ` prefix survives: the stream is the only difference,
        so a consumer grepping stderr for it keeps working."""
        with patch.dict(os.environ, {}, clear=True):
            _out, err, _ = self.run_fail("boom")
        self.assertTrue(err.startswith("Error: boom"))

    def test__no_traceback_without_the_env_var(self):
        """Verify ordinary users are not shown a stack."""
        exc = ValueError("inner")
        with patch.dict(os.environ, {}, clear=True):
            _out, err, _ = self.run_fail("boom", exc)
        self.assertNotIn("Traceback", err)

    def test__traceback_when_debug_is_set(self):
        """Verify a real exception can be diagnosed. The % outage surfaced as a bare
        `unsupported format character 'w'` with no indication of which module,
        function or docstring produced it."""
        try:
            raise ValueError("inner")
        except ValueError as e:
            exc = e
        with patch.dict(os.environ, {sp.DEBUG_ENV_VAR: "1"}):
            _out, err, _ = self.run_fail("boom", exc)
        self.assertIn("Traceback", err)
        self.assertIn("ValueError", err)

    def test__message_precedes_the_traceback(self):
        """Verify the readable one-liner is not buried under the stack."""
        try:
            raise ValueError("inner")
        except ValueError as e:
            exc = e
        with patch.dict(os.environ, {sp.DEBUG_ENV_VAR: "1"}):
            _out, err, _ = self.run_fail("boom", exc)
        self.assertLess(err.index("Error: boom"), err.index("Traceback"))


class FailWithUsageTests(unittest.TestCase):
    """Testing fail_with_usage()"""

    def run_fail(self, *args, **kwargs):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            with self.assertRaises(SystemExit) as cm:
                sp.fail_with_usage(*args, **kwargs)
        return out.getvalue(), err.getvalue(), cm.exception.code

    def test__message_and_help_both_go_to_stderr(self):
        """Verify the error and the parser's own help print together, so a bad
        invocation is not left to guess `-h` for itself."""
        parser = sp.DyingArgumentParser(prog="demo")
        parser.add_argument("--flag")
        out, err, _ = self.run_fail("boom", parser)
        self.assertEqual(out, "")
        self.assertIn("Error: boom", err)
        self.assertIn("usage: demo", err)
        self.assertIn("--flag", err)

    def test__the_message_precedes_the_help(self):
        """Verify the readable one-liner is not buried under the usage text."""
        parser = sp.DyingArgumentParser(prog="demo")
        _out, err, _ = self.run_fail("boom", parser)
        self.assertLess(err.index("Error: boom"), err.index("usage:"))

    def test__exit_code_is_one(self):
        """Verify a bad invocation exits the same way every other failure does."""
        parser = sp.DyingArgumentParser(prog="demo")
        _out, _err, code = self.run_fail("boom", parser)
        self.assertEqual(code, 1)

    def test__no_parser_still_reports_the_message(self):
        """Verify a caller that has no parser to show (defensive: every real
        ArgumentError carries one) still reports the error rather than crashing."""
        out, err, _ = self.run_fail("boom", None)
        self.assertEqual(out, "")
        self.assertIn("Error: boom", err)


class VersionTests(unittest.TestCase):
    """Testing __version__ and --version"""

    def test__version_is_a_dotted_number(self):
        """Verify it parses, since the comparator splits on dots."""
        self.assertRegex(sp.__version__, r"^\d+(\.\d+)*$")

    def test__version_flag_reports_both_versions_and_the_resolved_path(self):
        """Verify the question `--version` exists to answer: WHICH SubParsley am I
        running. With a sibling-directory default and an installable package,
        having two on a machine is easy."""
        out = io.StringIO()
        with patch.dict(os.environ, {"PROJECT_NAME": "demo", "PROJECT_VERSION": "1.2"}):
            with redirect_stdout(out):
                self.assertEqual(sp.main(["--version"]), 0)
        text = out.getvalue()
        self.assertIn("demo 1.2", text)
        self.assertIn(sp.__version__, text)
        self.assertIn("SubParsley.py", text)

    def test__version_works_without_a_consumer_version(self):
        """Verify a consumer that declares no version still gets output."""
        out = io.StringIO()
        with patch.dict(os.environ, {"PROJECT_NAME": "demo"}, clear=True):
            with redirect_stdout(out):
                sp.main(["--version"])
        self.assertIn(sp.__version__, out.getvalue())


class CheckRequirementTests(unittest.TestCase):
    """Testing the consumer-declared compatibility gate.

    The consumer declares and SubParsley checks, so every consumer gets it for
    free and none reimplements version parsing.
    """

    def fails(self, requirement, found):
        err = io.StringIO()
        with patch.dict(os.environ, {}, clear=True):
            with redirect_stderr(err):
                with self.assertRaises(SystemExit):
                    sp.check_requirement(requirement, found=found)
        return err.getvalue()

    def test__no_requirement_is_not_checked(self):
        """Verify an undeclared requirement is silence, not a failure."""
        sp.check_requirement("", found="0.3.0")
        sp.check_requirement(None, found="0.3.0")

    def test__a_satisfied_requirement_passes(self):
        """Verify the ordinary case."""
        sp.check_requirement(">=0.3,<0.4", found="0.3.0")
        sp.check_requirement(">=0.2", found="0.3.0")

    def test__too_old_is_refused(self):
        """Verify a lower bound is enforced."""
        self.assertIn("too old", self.fails(">=0.9", "0.3.0"))

    def test__too_new_is_refused(self):
        """Verify an upper bound is enforced — a consumer pinning <0.4 means it."""
        self.assertIn("too new", self.fails(">=0.1,<0.2", "0.3.0"))

    def test__the_message_names_the_resolved_path(self):
        """Verify it says WHICH SubParsley failed, since two checkouts is the
        normal state given the sibling-directory default."""
        err = io.StringIO()
        with patch.dict(os.environ, {}, clear=True):
            with redirect_stderr(err):
                with self.assertRaises(SystemExit):
                    sp.check_requirement(">=9.0", found="0.3.0", source="/somewhere/SubParsley.py")
        self.assertIn("/somewhere/SubParsley.py", err.getvalue())

    def test__an_unsupported_clause_is_refused_rather_than_ignored(self):
        """Verify `~=` or `==` fails loudly. Silently ignoring a clause would mean
        a consumer believes it is protected when it is not."""
        self.assertIn("Unsupported", self.fails("~=0.3", "0.3.0"))

    def test__a_malformed_version_is_refused(self):
        """Verify garbage in the requirement is caught before comparison."""
        self.assertIn("Malformed", self.fails(">=zero", "0.3.0"))

    def test__multi_digit_components_compare_numerically(self):
        """Verify 0.10 > 0.9, which a string comparison gets wrong."""
        sp.check_requirement(">=0.9", found="0.10.0")
        self.assertIn("too old", self.fails(">=0.10", "0.9.0"))


class ResolveConfigTests(unittest.TestCase):
    """Testing the PROJECT_* contract"""

    def test__an_unset_project_dir_falls_back_to_subparsleys_own_directory(self):
        """Verify the fallback is reachable. `Path("") or fallback` never took it:
        Path("") is Path("."), which is truthy, so an unset PROJECT_DIR silently
        meant the current working directory."""
        with patch.dict(os.environ, {}, clear=True):
            project_dir, _name, _desc = sp.resolve_config()
        self.assertEqual(project_dir, Path(sp.__file__).parent)


class MainArgumentErrorTests(ModuleTreeTestCase):
    """Testing that main() shows the RIGHT LEVEL of help on a bad invocation:
    top-level for a missing noun, the noun's for a missing verb, the verb's
    for a missing/invalid argument."""

    def setUp(self):
        super().setUp()
        self.tree({
            "demo.py": self.verb("Do a thing", ns="demo",
                                 args={"name": "The name"}, params="name: str"),
        })

    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        env = {"PROJECT_DIR": str(self.root), "PROJECT_NAME": "prog"}
        with patch.dict(os.environ, env, clear=True):
            with redirect_stdout(out), redirect_stderr(err):
                with self.assertRaises(SystemExit) as cm:
                    sp.main(argv)
        return out.getvalue(), err.getvalue(), cm.exception.code

    def test__no_arguments_shows_the_top_level_help(self):
        """Verify `prog` alone shows the same help `prog -h` would."""
        _out, err, code = self.run_main([])
        self.assertEqual(code, 1)
        self.assertIn("Error: the following arguments are required: noun", err)
        self.assertIn("usage: prog", err)
        self.assertIn("demo", err)  # the noun is listed as a choice

    def test__a_missing_verb_shows_the_noun_level_help(self):
        """Verify `prog demo` shows the same help `prog demo -h` would, not the
        top-level one."""
        _out, err, code = self.run_main(["demo"])
        self.assertEqual(code, 1)
        self.assertIn("Error: the following arguments are required: verb", err)
        self.assertIn("usage: prog demo", err)
        self.assertIn("run", err)  # the verb is listed as a choice

    def test__a_missing_argument_shows_the_verb_level_help(self):
        """Verify `prog demo run` shows the same help `prog demo run -h`
        would, naming the missing flag rather than the noun/verb choices."""
        _out, err, code = self.run_main(["demo", "run"])
        self.assertEqual(code, 1)
        self.assertIn("--name", err)
        self.assertIn("usage: prog demo run", err)

    def test__an_empty_project_dir_also_falls_back(self):
        """Verify an explicitly empty value is treated as unset, not as CWD."""
        with patch.dict(os.environ, {"PROJECT_DIR": "  "}):
            project_dir, _name, _desc = sp.resolve_config()
        self.assertEqual(project_dir, Path(sp.__file__).parent)

    def test__an_explicit_project_dir_is_used(self):
        """Verify the ordinary case still works."""
        with patch.dict(os.environ, {"PROJECT_DIR": "/tmp"}):
            project_dir, _name, _desc = sp.resolve_config()
        self.assertEqual(project_dir, Path("/tmp"))


if __name__ == "__main__":
    unittest.main()
