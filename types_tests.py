"""Tests for annotation-driven argparse type conversion."""
import unittest
from decimal import Decimal
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

    def test__garbage_raises_ValueError_not_InvalidOperation(self):
        """Verify the exception type. argparse._get_value catches only
        ArgumentTypeError, TypeError and ValueError, so an InvalidOperation would
        escape as a raw traceback instead of the framework's `Error: ...` path."""
        with self.assertRaises(ValueError):
            sp._decimal_arg("abc")

    def test__nan_and_infinity_are_rejected(self):
        """Verify --shares nan cannot post a NaN row."""
        for value in ("nan", "Infinity", "-Infinity"):
            with self.assertRaises(ValueError, msg=value):
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


if __name__ == "__main__":
    unittest.main()
