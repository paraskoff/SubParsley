"""Tests for docstring metadata extraction and verb collection."""
import os
import unittest
from unittest.mock import patch

import SubParsley as sp
from tests import ModuleTreeTestCase, sandboxed_imports


class ExtractFunctionMetadataTests(unittest.TestCase):
    """Testing extract_function_metadata"""

    def test__missing_docstring_yields_no_description(self):
        """Verify an undocumented function is simply not a command."""
        def f():
            pass
        desc, arg_help, ns = sp.extract_function_metadata(f)
        self.assertIsNone(desc)
        self.assertEqual(arg_help, {})
        self.assertIsNone(ns)

    def test__desc_survives_an_embedded_colon(self):
        """Verify @desc: text containing a colon is not truncated at it. A plain
        split(":") dropped everything after the SECOND colon."""
        def f():
            """
            @ns: demo
            @desc: Render a note: fill placeholders
            """
        desc, _arg_help, _ns = sp.extract_function_metadata(f)
        self.assertEqual(desc, "Render a note: fill placeholders")

    def test__arg_help_survives_an_embedded_colon(self):
        """Verify @arg: help text containing a colon is not truncated at it."""
        def f(x: str):
            """
            @ns: demo
            @desc: ok
            @arg: x Path to file: absolute or relative
            """
        _, arg_help, _ = sp.extract_function_metadata(f)
        self.assertEqual(arg_help["x"].help, "Path to file: absolute or relative")

    def test__ns_survives_an_embedded_colon(self):
        """Verify @ns: value containing a colon is not truncated at it."""
        def f():
            """
            @ns: demo:sub
            @desc: ok
            """
        _desc, _arg_help, ns = sp.extract_function_metadata(f)
        self.assertEqual(ns, "demo:sub")

    def test__bang_desc_suppresses_the_command(self):
        """Verify `!@desc:` opts a function out entirely."""
        def f():
            """
            @ns: demo
            !@desc: Deliberately not a command
            """
        desc, _arg_help, _ns = sp.extract_function_metadata(f)
        self.assertIsNone(desc)

    def test__bang_desc_wins_regardless_of_order(self):
        """Verify suppression beats a real @desc: appearing before it."""
        def f():
            """
            @desc: Looks like a command
            !@desc: but is not
            """
        desc, _arg_help, _ns = sp.extract_function_metadata(f)
        self.assertIsNone(desc)


class PhantomVerbTests(ModuleTreeTestCase):
    """Testing that a re-imported function does not register twice.

    inspect.getmembers returns imported names too, so `from helpers import render`
    where render carries @desc: would publish a phantom verb in the importing
    module's namespace as well as its own.
    """

    def nouns(self):
        with sandboxed_imports():
            parser = sp.setup_cli(self.root)
        return parser._subparsers._group_actions[0].choices

    def test__a_locally_defined_verb_registers(self):
        """Verify the ordinary case still works."""
        self.tree({"mine.py": self.verb("Do a thing", ns="mine")})
        self.assertIn("mine", self.nouns())

    def test__a_reimported_verb_does_not_register_again(self):
        """Verify importing another module's command does not duplicate it."""
        self.tree({
            "origin.py": self.verb("Do a thing", ns="origin"),
            "importer.py": "from origin import run\n",
        })
        nouns = self.nouns()
        self.assertIn("origin", nouns)
        self.assertEqual(len(nouns["origin"]._subparsers._group_actions[0].choices), 1)

    def test__a_reimported_verb_does_not_leak_into_the_importers_namespace(self):
        """Verify the phantom does not appear under the importing module's own noun
        when the function carries no @ns:."""
        self.tree({
            "origin.py": 'def run():\n    """\n    @desc: Do a thing\n    """\n',
            "importer.py": "from origin import run\n",
        })
        self.assertNotIn("importer", self.nouns())


class ArgSpecGrammarTests(unittest.TestCase):
    """Testing the bracketed `@arg:` spec.

    One extended grammar rather than a family of new tags: it keeps an
    argument's whole schema on one greppable line, and degrades survivably —
    an older SubParsley renders `[-p]` as literal help text instead of crashing.
    """

    def spec(self, line, param="x"):
        def f(x: str = ""):
            pass
        f.__doc__ = f"\n@desc: d\n@arg: {param} {line}\n"
        _desc, args, _ns = sp.extract_function_metadata(f)
        return args[param]

    def test__a_plain_arg_line_is_unchanged(self):
        """Verify the original grammar still means exactly what it did."""
        spec = self.spec("Just some help text")
        self.assertEqual(spec.help, "Just some help text")
        self.assertIsNone(spec.short)
        self.assertIsNone(spec.choices)
        self.assertFalse(spec.repeat)

    def test__an_explicit_short_flag_is_parsed(self):
        """Verify `[-p]` declares a short flag and is stripped from the help."""
        spec = self.spec("[-p] Portfolio name")
        self.assertEqual(spec.short, "p")
        self.assertEqual(spec.help, "Portfolio name")

    def test__choices_are_pipe_separated(self):
        """Verify pipes, not commas — a choice may legitimately contain a comma."""
        self.assertEqual(self.spec("[choices=BUY|SELL] Action").choices, ["BUY", "SELL"])

    def test__repeat_and_nargs_are_parsed(self):
        """Verify the list-valued modifiers."""
        self.assertTrue(self.spec("[repeat] Tags").repeat)
        self.assertEqual(self.spec("[nargs=*] Tags").nargs, "*")

    def test__several_modifiers_combine(self):
        """Verify a spec can carry more than one thing."""
        spec = self.spec("[-a choices=BUY|SELL] Trade action")
        self.assertEqual((spec.short, spec.choices, spec.help),
                         ("a", ["BUY", "SELL"], "Trade action"))

    def test__a_bracket_later_in_the_help_is_not_a_spec(self):
        """Verify the bracket is only special in FIRST position, so ordinary help
        text containing brackets is left alone."""
        spec = self.spec("Path to file [absolute or relative]")
        self.assertEqual(spec.help, "Path to file [absolute or relative]")
        self.assertIsNone(spec.short)

    def test__an_unclosed_bracket_is_help_text_not_a_crash(self):
        """Verify malformed input degrades rather than raising."""
        self.assertEqual(self.spec("[-p Portfolio name").help, "[-p Portfolio name")

    def test__an_unknown_modifier_warns_rather_than_being_ignored(self):
        """Verify a typo'd modifier is reported. Silently dropping `[choices=...]`
        would look like it worked."""
        import io
        from contextlib import redirect_stderr
        err = io.StringIO()
        with patch.dict(os.environ, {}, clear=True):
            with redirect_stderr(err):
                spec = self.spec("[bogus=1] Some help")
        self.assertIn("unknown modifier", err.getvalue())
        self.assertEqual(spec.help, "Some help")

    def test__str_of_a_spec_is_its_help(self):
        """Verify ArgSpec degrades to its help text where a string is expected."""
        self.assertEqual(str(self.spec("[-p] Portfolio name")), "Portfolio name")

    def test__an_arg_line_with_no_help_still_parses(self):
        """Verify a bare `@arg: name` does not crash the split."""
        self.assertEqual(self.spec("").help, "")


if __name__ == "__main__":
    unittest.main()
