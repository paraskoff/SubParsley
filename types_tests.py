"""Tests for annotation-driven argparse type conversion."""
import argparse
import unittest
from decimal import Decimal
from enum import Enum
from typing import Optional

import SubParsley as sp
from parser_tests import build


class DecimalConverterTests(unittest.TestCase):
    """Testing the Decimal branch of _get_type_converter"""

    def test__a_decimal_annotation_gets_a_converter(self):
        """Verify Decimal is recognised at all."""
        self.assertIs(sp._get_type_converter(Decimal), sp._decimal_arg)

    def test__conversion_is_exact(self):
        """Verify the entire premise. The value is built from argparse's raw string,
        so --price 0.1 is Decimal('0.1') and never Decimal(0.1)'s binary expansion."""
        self.assertEqual(sp._decimal_arg("0.1"), Decimal("0.1"))
        self.assertNotEqual(sp._decimal_arg("0.1"), Decimal(0.1))

    def test__precision_beyond_float_survives(self):
        """Verify a value a float could not hold arrives intact — the concrete reason
        to convert in the framework rather than at the service boundary."""
        raw = "1234567890123456789.05"
        self.assertEqual(sp._decimal_arg(raw), Decimal(raw))
        self.assertNotEqual(Decimal(str(float(raw))), Decimal(raw))

    def test__garbage_raises_ArgumentTypeError_not_InvalidOperation(self):
        """Verify the exception type. argparse._get_value catches only
        ArgumentTypeError, TypeError and ValueError, so an InvalidOperation would
        escape as a raw traceback instead of the framework's `Error: ...` path."""
        with self.assertRaises(argparse.ArgumentTypeError):
            sp._decimal_arg("abc")

    def test__the_error_message_does_not_leak_the_converter_name(self):
        """Verify the user sees the value, not an internal function name. argparse
        uses an ArgumentTypeError's message verbatim, whereas a ValueError falls
        back to `invalid _decimal_arg value: 'abc'`."""
        def f(price: Decimal = Decimal(0)):
            """
            @desc: Set a price
            @arg: price Price
            """
        with self.assertRaises(sp.ArgumentError) as cm:
            build(f).parse_args(["demo", "run", "--price", "abc"])
        self.assertIn("is not a decimal number", str(cm.exception))
        self.assertNotIn("_decimal_arg", str(cm.exception))

    def test__nan_and_infinity_are_rejected(self):
        """Verify --shares nan cannot post a NaN row."""
        for value in ("nan", "Infinity", "-Infinity"):
            with self.assertRaises(argparse.ArgumentTypeError, msg=value):
                sp._decimal_arg(value)

    def test__a_bad_value_goes_through_the_frameworks_error_path(self):
        """Verify end to end: DyingArgumentParser turns it into ArgumentError, which
        main() reports as `Error: ...` and exits 1."""
        def f(price: Decimal = Decimal(0)):
            """
            @desc: Set a price
            @arg: price Price
            """
        parser = build(f)
        with self.assertRaises(sp.ArgumentError):
            parser.parse_args(["demo", "run", "--price", "abc"])

    def test__a_good_value_parses_to_a_decimal(self):
        """Verify the happy path through a real parser."""
        def f(price: Decimal = Decimal(0)):
            """
            @desc: Set a price
            @arg: price Price
            """
        args = build(f).parse_args(["demo", "run", "--price", "132.40"])
        self.assertEqual(args.price, Decimal("132.40"))
        self.assertIsInstance(args.price, Decimal)


class OptionalUnwrappingTests(unittest.TestCase):
    """Testing that Optional[X] still converts as X.

    A prerequisite, not a nicety: kolobar writes `target_dir: str = None` today,
    and the moment those are corrected to the accurate Optional[str] an
    unwrapping-free lookup silently drops the converter for Optional[int].
    """

    def test__optional_int_converts(self):
        """Verify Optional[int] behaves as int."""
        self.assertIs(sp._get_type_converter(Optional[int]), int)

    def test__pep604_union_converts(self):
        """Verify the `int | None` spelling works too."""
        self.assertIs(sp._get_type_converter(int | None), int)

    def test__optional_decimal_converts(self):
        """Verify the combination this migration needs."""
        self.assertIs(sp._get_type_converter(Optional[Decimal]), sp._decimal_arg)

    def test__optional_bool_still_gets_boolean_optional_action(self):
        """Verify Optional[bool] keeps --flag/--no-flag rather than acquiring a
        converter, which would break the action."""
        self.assertIsNone(sp._get_type_converter(Optional[bool]))

        def f(flag: Optional[bool] = None):
            """
            @desc: Toggle
            @arg: flag A toggle
            """
        parser = build(f)
        self.assertTrue(parser.parse_args(["demo", "run", "--flag"]).flag)
        self.assertFalse(parser.parse_args(["demo", "run", "--no-flag"]).flag)

    def test__optional_str_stays_none_by_default(self):
        """Verify an omitted Optional[str] is None, not the string 'None'."""
        def f(name: Optional[str] = None):
            """
            @desc: Do a thing
            @arg: name A name
            """
        self.assertIsNone(build(f).parse_args(["demo", "run"]).name)

    def test__a_three_way_union_is_left_alone(self):
        """Verify only the Optional shape is unwrapped: `int | str | None` is
        ambiguous and must not silently pick one."""
        self.assertIsNone(sp._get_type_converter(int | str | None))

    def test__a_plain_annotation_is_unaffected(self):
        """Verify the ordinary path did not change."""
        self.assertIs(sp._get_type_converter(int), int)
        self.assertIs(sp._get_type_converter(float), float)
        self.assertIsNone(sp._get_type_converter(str))


class EnumConverterTests(unittest.TestCase):
    """Testing Enum-annotated parameters.

    Without a converter an Enum parameter silently arrived as a raw string,
    which then never compared equal to any member — the bug class that once
    inverted every BUY into a SELL in the consumer's ledger.
    """

    class Action(Enum):
        BUY = "BUY"
        SELL = "SELL"

    def verb(self):
        def f(action: EnumConverterTests.Action = None):
            """
            @desc: Do a trade
            @arg: action Trade action
            """
        return f

    def test__an_enum_annotation_gets_a_converter(self):
        """Verify Enum is recognised at all."""
        self.assertIsNotNone(sp._get_type_converter(self.Action))

    def test__the_value_converts_to_the_member(self):
        """Verify users type the VALUE, which is what the domain calls it and what
        ends up in the data — not the member name."""
        args = build(self.verb()).parse_args(["demo", "run", "--action", "BUY"])
        self.assertIs(args.action, self.Action.BUY)

    def test__an_invalid_value_is_refused_listing_the_valid_ones(self):
        """Verify a typo is self-correcting rather than silently passed through."""
        with self.assertRaises(sp.ArgumentError) as cm:
            build(self.verb()).parse_args(["demo", "run", "--action", "SIDEWAYS"])
        self.assertIn("BUY, SELL", str(cm.exception))

    def test__the_accepted_values_appear_in_help(self):
        """Verify --help advertises them, so the CLI is discoverable."""
        verb = (build(self.verb())._subparsers._group_actions[0].choices["demo"]
                ._subparsers._group_actions[0].choices["run"])
        self.assertIn("{BUY,SELL}", verb.format_help())

    def test__optional_enum_converts_too(self):
        """Verify the Optional wrapper does not lose the converter."""
        self.assertIsNotNone(sp._get_type_converter(Optional[self.Action]))

    def test__enum_choices_lists_values_not_names(self):
        """Verify the helper reports what a user actually types."""
        self.assertEqual(sp.enum_choices(self.Action), ["BUY", "SELL"])


class ExplicitChoicesTests(unittest.TestCase):
    """Testing `choices=` in the bracketed @arg: spec"""

    def test__a_valid_choice_is_accepted(self):
        """Verify the ordinary path."""
        def f(kind: str = "supplement"):
            """
            @desc: Start a protocol
            @arg: kind [choices=supplement|fitness|nutrition] Protocol kind
            """
        args = build(f).parse_args(["demo", "run", "--kind", "fitness"])
        self.assertEqual(args.kind, "fitness")

    def test__an_invalid_choice_is_refused(self):
        """Verify argparse rejects it before the dispatcher runs."""
        def f(kind: str = "supplement"):
            """
            @desc: Start a protocol
            @arg: kind [choices=supplement|fitness] Protocol kind
            """
        with self.assertRaises(sp.ArgumentError):
            build(f).parse_args(["demo", "run", "--kind", "nonsense"])

    def test__choices_are_converted_with_the_parameter_type(self):
        """Verify `choices=1|2` on an int holds ints. argparse compares the
        CONVERTED value, so string choices would reject every input."""
        def f(level: int = 1):
            """
            @desc: Set a level
            @arg: level [choices=1|2|3] Level
            """
        self.assertEqual(build(f).parse_args(["demo", "run", "--level", "2"]).level, 2)


if __name__ == "__main__":
    unittest.main()
