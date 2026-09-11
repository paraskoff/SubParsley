"""Tests for main(), fail() and the debug switch."""
import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

import SubParsley as sp


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


if __name__ == "__main__":
    unittest.main()
