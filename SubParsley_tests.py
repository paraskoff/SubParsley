"""Regression tests for the CLI-schema and boolean-flag fixes.

SubParsley has no other test infrastructure; this is deliberately a single
stdlib-only file exercising the three behaviors documented in the README's
"Behavior consumers must design around" section, so a future edit to
extract_function_metadata / create_verb_parser / main's error handling cannot
silently reintroduce any of them.
"""
import argparse
import unittest

import SubParsley as sp


class ExtractFunctionMetadataColonTests(unittest.TestCase):
    """Testing extract_function_metadata's handling of colons in tag text"""

    def test__desc_survives_an_embedded_colon(self):
        """Verify @desc: text containing a colon is not truncated at it."""
        def f():
            """
            @ns: demo
            @desc: Render a note: fill placeholders
            """
        desc, _, _ = sp.extract_function_metadata(f)
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
        self.assertEqual(arg_help["x"], "Path to file: absolute or relative")

    def test__ns_survives_an_embedded_colon(self):
        """Verify @ns: value containing a colon is not truncated at it (edge case,
        namespaces should not normally contain one, but the parser must not
        special-case @ns differently from @desc/@arg)."""
        def f():
            """
            @ns: demo: sub
            @desc: ok
            """
        _, _, ns = sp.extract_function_metadata(f)
        self.assertEqual(ns, "demo: sub")


class CreateVerbParserBooleanFlagTests(unittest.TestCase):
    """Testing create_verb_parser's handling of bool-annotated parameters"""

    def _build(self, func, arg_help, default_ns="demo"):
        parser = sp.DyingArgumentParser()
        subparsers = parser.add_subparsers()
        noun = subparsers.add_parser(default_ns)
        verbs = noun.add_subparsers()
        sp.create_verb_parser(verbs, func.__name__, func, "desc", arg_help, default_ns)
        return parser

    def test__bool_default_true_can_be_turned_off(self):
        """Verify a bool parameter defaulting to True can be set to False via --no-<flag>."""
        def verb(verbose: bool = True):
            pass
        parser = self._build(verb, {"verbose": "v"})
        self.assertTrue(parser.parse_args(["demo", "verb"]).verbose)
        self.assertFalse(parser.parse_args(["demo", "verb", "--no-verbose"]).verbose)

    def test__bool_default_false_can_be_turned_on(self):
        """Verify a bool parameter defaulting to False can still be set to True via --flag."""
        def verb(force: bool = False):
            pass
        parser = self._build(verb, {"force": "f"})
        self.assertFalse(parser.parse_args(["demo", "verb"]).force)
        self.assertTrue(parser.parse_args(["demo", "verb", "--force"]).force)


class DyingArgumentParserErrorTests(unittest.TestCase):
    """Testing that a parse failure raises ArgumentError instead of exiting directly"""

    def test__invalid_numeric_value_raises_argument_error(self):
        """Verify a bad --shares value raises ArgumentError rather than calling
        sys.exit(2) directly, so main() can report it through its own Error:
        message and exit(1)."""
        def trade(ticker: str, shares: float):
            pass
        parser = sp.DyingArgumentParser()
        subparsers = parser.add_subparsers()
        noun = subparsers.add_parser("portfolio")
        verbs = noun.add_subparsers()
        sp.create_verb_parser(verbs, "trade", trade, "trade",
                               {"ticker": "t", "shares": "s"}, "portfolio")
        with self.assertRaises(sp.ArgumentError):
            parser.parse_args(["portfolio", "trade", "-t", "X", "-s", "abc"])

    def test__valid_arguments_do_not_raise(self):
        """Verify a well-formed invocation parses normally without raising."""
        def trade(ticker: str, shares: float):
            pass
        parser = sp.DyingArgumentParser()
        subparsers = parser.add_subparsers()
        noun = subparsers.add_parser("portfolio")
        verbs = noun.add_subparsers()
        sp.create_verb_parser(verbs, "trade", trade, "trade",
                               {"ticker": "t", "shares": "s"}, "portfolio")
        args = parser.parse_args(["portfolio", "trade", "-t", "NVDA", "-s", "10"])
        self.assertEqual(args.ticker, "NVDA")
        self.assertEqual(args.shares, 10.0)


if __name__ == "__main__":
    unittest.main()
