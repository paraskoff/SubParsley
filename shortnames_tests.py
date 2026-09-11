"""Tests for short-flag derivation and the reservations that keep it safe."""
import io
import unittest
from contextlib import redirect_stderr

import SubParsley as sp
from parser_tests import build


class GenerateBaseShortNameTests(unittest.TestCase):
    """Testing generate_base_short_name"""

    def test__snake_case_takes_each_initial(self):
        """Verify spec_path -> sp."""
        self.assertEqual(sp.generate_base_short_name("spec_path"), "sp")

    def test__camel_case_takes_each_initial(self):
        """Verify specPath -> sp, same as the snake form."""
        self.assertEqual(sp.generate_base_short_name("specPath"), "sp")

    def test__single_word_takes_one_letter(self):
        """Verify path -> p."""
        self.assertEqual(sp.generate_base_short_name("path"), "p")

    def test__empty_name_yields_nothing(self):
        """Verify the degenerate case returns '' rather than raising."""
        self.assertEqual(sp.generate_base_short_name(""), "")


class ReservedShortNameTests(unittest.TestCase):
    """Testing that -h can never be stolen from argparse"""

    def test__an_h_initial_parameter_does_not_claim_dash_h(self):
        """Verify a `host` parameter cannot take -h. add_argument('-h', ...) raises
        at PARSER CONSTRUCTION time, so it would take down the entire CLI rather
        than one verb.

        It still gets a short flag — the derivation walks longer prefixes, so
        `host` becomes -ho. The previous name for this test said "gets no short
        flag", which was never what happened."""
        used = set(sp.RESERVED_SHORT_NAMES)
        self.assertEqual(sp.generate_unique_short_name("host", used), "ho")

    def test__a_parameter_named_h_gets_nothing(self):
        """Verify the one case that genuinely yields no flag: there is no longer
        prefix to fall back to."""
        used = set(sp.RESERVED_SHORT_NAMES)
        self.assertIsNone(sp.generate_unique_short_name("h", used))

    def test__the_long_form_still_works(self):
        """Verify losing the short flag costs nothing else."""
        def f(host: str = "x"):
            """
            @desc: Connect
            @arg: host Hostname
            """
        parser = build(f)
        self.assertEqual(parser.parse_args(["demo", "run", "--host", "a"]).host, "a")

    def test__help_still_works_on_that_verb(self):
        """Verify -h remains argparse's."""
        def f(host: str = "x"):
            """
            @desc: Connect
            @arg: host Hostname
            """
        verb = build(f)._subparsers._group_actions[0].choices["demo"]
        text = verb._subparsers._group_actions[0].choices["run"].format_help()
        self.assertIn("-h, --help", text)


class DerivationStabilityTests(unittest.TestCase):
    """Pinning today's derived short flags for kolobar's real signatures.

    These are the CLI's public surface: a scripted `klbr` invocation depends on
    -p meaning what it meant yesterday. Reserving -h shifted nothing, and this
    is the baseline that proves it.
    """

    def shorts(self, func):
        parser = build(func)
        verb = (parser._subparsers._group_actions[0].choices["demo"]
                ._subparsers._group_actions[0].choices["run"])
        found = {}
        for action in verb._actions:
            if action.dest in ("help",):
                continue
            short = [o for o in action.option_strings if not o.startswith("--")]
            found[action.dest] = short[0] if short else None
        return found

    def test__sbor_init(self):
        """Verify -p/--path and -st/--schema-type are unchanged."""
        def f(path: str, schema_type: str):
            """
            @desc: Create a sbor
            @arg: path Path
            @arg: schema_type Type
            """
        self.assertEqual(self.shorts(f), {"path": "-p", "schema_type": "-st"})

    def test__allocation_add_asset(self):
        """Verify the multi-character forms -tp and -ac survive."""
        def f(sleeve: str, ticker: str, target_pct: float, asset_class: str = "Equity",
              portfolio: str = None):
            """
            @desc: Add an asset
            @arg: sleeve Sleeve
            @arg: ticker Ticker
            @arg: target_pct Target
            @arg: asset_class Class
            @arg: portfolio Portfolio
            """
        self.assertEqual(self.shorts(f), {
            "sleeve": "-s", "ticker": "-t", "target_pct": "-tp",
            "asset_class": "-ac", "portfolio": "-p"})

    def test__quote_set_disambiguates_price_from_portfolio(self):
        """Verify the documented collision walk: price takes -p by position, so
        portfolio falls through to -po. This is exactly the instability that makes
        short flags unsafe to document, and it is pinned rather than endorsed."""
        def f(ticker: str, price: float, portfolio: str = None):
            """
            @desc: Set a price
            @arg: ticker Ticker
            @arg: price Price
            @arg: portfolio Portfolio
            """
        self.assertEqual(self.shorts(f),
                         {"ticker": "-t", "price": "-p", "portfolio": "-po"})


class ShortFlagConflictTests(unittest.TestCase):
    """Testing that a construction-time clash degrades rather than aborting"""

    def test__a_conflict_warns_and_keeps_the_long_flag(self):
        """Verify the CLI survives an unexpected clash. Simulated by forcing two
        parameters onto the same short name."""
        def f(alpha: str = "a", beta: str = "b"):
            """
            @desc: Two things
            @arg: alpha First
            @arg: beta Second
            """
        original = sp.generate_unique_short_name
        try:
            sp.generate_unique_short_name = lambda name, used: "x"
            err = io.StringIO()
            with redirect_stderr(err):
                parser = build(f)
        finally:
            sp.generate_unique_short_name = original
        self.assertIn("dropping short flag", err.getvalue())
        args = parser.parse_args(["demo", "run", "--alpha", "1", "--beta", "2"])
        self.assertEqual((args.alpha, args.beta), ("1", "2"))


if __name__ == "__main__":
    unittest.main()
