"""Tests for parser construction: help escaping, argument shape, bool flags."""
import argparse
import unittest

import SubParsley as sp


def build(func, verb="run", noun="demo"):
    """Builds a full parser exposing one verb, the way setup_cli would."""
    parser = sp.DyingArgumentParser(prog="t")
    subparsers = parser.add_subparsers(dest="noun", required=True)
    desc, arg_help, _ns = sp.extract_function_metadata(func)
    sp.create_noun_parser(subparsers, noun, [(verb, func, desc, arg_help)])
    return parser


class EscapeHelpTests(unittest.TestCase):
    """Testing escape_help"""

    def test__percent_is_doubled(self):
        """Verify a lone % becomes %% so argparse's formatter leaves it alone."""
        self.assertEqual(sp.escape_help("100% done"), "100%% done")

    def test__text_without_percent_is_unchanged(self):
        """Verify the common case is untouched."""
        self.assertEqual(sp.escape_help("plain text"), "plain text")

    def test__empty_and_none_pass_through(self):
        """Verify no crash on the absent-description path."""
        self.assertEqual(sp.escape_help(""), "")
        self.assertIsNone(sp.escape_help(None))


class PercentInHelpTextTests(unittest.TestCase):
    """Testing that a % in consumer docstrings cannot break --help.

    Regression for the live outage: kolobar's allocation namespace carried
    `@desc: ...adds up to 100% with no over-allocated sleeve`, and
    `klbr allocation --help` died with `unsupported format character 'w'`,
    making all five of its verbs undiscoverable.
    """

    def test__percent_in_desc_does_not_break_noun_help(self):
        """Verify the noun's help renders — this is the exact crash."""
        def f():
            """
            @desc: Check that the target allocation adds up to 100% with no over-allocated sleeve
            """
        parser = build(f)
        text = parser.format_help()
        self.assertIn("demo", text)

    def test__percent_in_desc_renders_a_single_percent_in_the_verb_list(self):
        """Verify the user sees `100%`, not `100%%`."""
        def f():
            """
            @desc: Adds up to 100% exactly
            """
        text = build(f)._subparsers._group_actions[0].choices["demo"].format_help()
        self.assertIn("100%", text)
        self.assertNotIn("100%%", text)

    def test__percent_in_description_is_not_double_escaped(self):
        """Verify description= is left raw: argparse does not expand it, so escaping
        there would show the user a literal `100%%`."""
        def f():
            """
            @desc: Adds up to 100% exactly
            """
        verb = build(f)._subparsers._group_actions[0].choices["demo"]
        text = verb._subparsers._group_actions[0].choices["run"].format_help()
        self.assertIn("100%", text)
        self.assertNotIn("100%%", text)

    def test__percent_in_arg_help_does_not_break_verb_help(self):
        """Verify @arg: text is escaped too. This is a SECOND exposure, missed in the
        original audit, and it fails differently: `TypeError: %d format: a real
        number is required, not dict`."""
        def f(target_pct: float = 0.0):
            """
            @desc: Set a target
            @arg: target_pct Percentage of the portfolio, e.g. 40% of total
            """
        verb = build(f)._subparsers._group_actions[0].choices["demo"]
        text = verb._subparsers._group_actions[0].choices["run"].format_help()
        self.assertIn("40%", text)
        self.assertNotIn("40%%", text)

    def test__argparse_interpolation_in_arg_help_is_neutralised(self):
        """Verify %(default)s is shown literally rather than interpolated. A docstring
        is consumer prose, not a format string; reaching argparse internals through
        it by accident is the bug, not a feature."""
        def f(name: str = "abc"):
            """
            @desc: Do a thing
            @arg: name Defaults to %(default)s
            """
        verb = build(f)._subparsers._group_actions[0].choices["demo"]
        text = verb._subparsers._group_actions[0].choices["run"].format_help()
        self.assertIn("%(default)s", text)
        self.assertNotIn("abc", text.split("Defaults to")[1][:20])


class BooleanFlagTests(unittest.TestCase):
    """Testing bool parameters become --flag/--no-flag (moved from SubParsley_tests)"""

    def test__bool_default_true_can_be_turned_off(self):
        """Verify --no-flag works, which store_true could never express."""
        def f(flag: bool = True):
            """
            @desc: Toggle
            @arg: flag A toggle
            """
        parser = build(f)
        self.assertFalse(parser.parse_args(["demo", "run", "--no-flag"]).flag)

    def test__bool_default_false_can_be_turned_on(self):
        """Verify --flag still works in the ordinary direction."""
        def f(flag: bool = False):
            """
            @desc: Toggle
            @arg: flag A toggle
            """
        parser = build(f)
        self.assertTrue(parser.parse_args(["demo", "run", "--flag"]).flag)



class DyingArgumentParserTests(unittest.TestCase):
    """Testing that a parse failure routes through the framework's error path.

    Restored here when the pre-split SubParsley_tests.py was folded in — argparse
    would otherwise print its own usage banner and exit(2), bypassing the
    `Error: ...` / exit 1 convention every other failure uses.
    """

    def parser(self):
        def f(count: int = 0):
            """
            @desc: Count things
            @arg: count How many
            """
        return build(f)

    def test__an_invalid_numeric_value_raises_ArgumentError(self):
        """Verify a bad --count is raised, not exited on."""
        with self.assertRaises(sp.ArgumentError):
            self.parser().parse_args(["demo", "run", "--count", "abc"])

    def test__an_unrecognized_flag_raises_ArgumentError(self):
        """Verify a typo'd flag takes the same path."""
        with self.assertRaises(sp.ArgumentError):
            self.parser().parse_args(["demo", "run", "--nope", "1"])

    def test__a_missing_required_argument_raises_ArgumentError(self):
        """Verify a missing required value does too."""
        def f(name: str):
            """
            @desc: Name a thing
            @arg: name The name
            """
        with self.assertRaises(sp.ArgumentError):
            build(f).parse_args(["demo", "run"])

    def test__valid_arguments_do_not_raise(self):
        """Verify the happy path is untouched, and the value is converted."""
        args = self.parser().parse_args(["demo", "run", "--count", "7"])
        self.assertEqual(args.count, 7)


if __name__ == "__main__":
    unittest.main()
