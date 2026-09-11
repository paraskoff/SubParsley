"""Tests for docstring metadata extraction and verb collection."""
import unittest

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


if __name__ == "__main__":
    unittest.main()
