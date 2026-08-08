#!/usr/bin/env python3
""" SubParsley 
    A lightweight, extensible, and reusable CLI framework for Python projects 
"""

import importlib
import inspect
import sys
import argparse
from pathlib import Path

def setup_cli(modules_dir: Path):
    # Main parser
    parser = argparse.ArgumentParser(description="Extensible CLI Tool")
    subparsers = parser.add_subparsers(dest="noun", title="Nouns", required=True)

    # Load all modules in the specified modules_dir
    sys.path.insert(0, str(modules_dir))
    for module_file in modules_dir.glob("*.py"):
        if module_file.name == "__init__.py":
            continue
        module_name = module_file.stem
        module = importlib.import_module(module_name)

        # Create a subparser for the noun (e.g., "trade")
        noun_parser = subparsers.add_parser(
            module_name,
            help=f"Commands for {module_name}",
        )
        noun_subparsers = noun_parser.add_subparsers(
            dest="verb",
            title="Verbs",
            required=True,
        )

        # Add subcommands for each method in the module
        for name, obj in inspect.getmembers(module):
            if inspect.isfunction(obj) and not name.startswith("_"):
                # Extract metadata from docstring
                doc = inspect.getdoc(obj) or ""
                desc = None
                arg_help = {}
                for line in doc.split("\n"):
                    line = line.strip()
                    if line.startswith("@desc:"):
                        desc = line.split(":")[1].strip()
                    if line.startswith("@arg:"):
                        parts = line.split(":")[1].strip().split(" ")
                        param_name = parts[0]
                        help_text = " ".join(parts[1:])
                        arg_help[param_name] = help_text

                # Create a subparser for the verb (e.g., "add" for add_trade)
                verb_parser = noun_subparsers.add_parser(
                    name,
                    help=desc or f"{name} {module_name}",
                    description=desc,
                )

                # Add arguments based on the function signature
                sig = inspect.signature(obj)
                for param_name, param in sig.parameters.items():
                    if param_name == "self":
                        continue
                    arg_name = f"--{param_name.replace('_', '-')}"
                    kwargs = {
                        "dest": param_name,
                        "help": arg_help.get(param_name, f"{param_name} for {module_name}"),
                    }
                    if param.default is not inspect.Parameter.empty:
                        kwargs["default"] = param.default
                    if param.annotation is not inspect.Parameter.empty:
                        if param.annotation == int:
                            kwargs["type"] = int
                        elif param.annotation == float:
                            kwargs["type"] = float
                        elif param.annotation == bool:
                            kwargs["action"] = "store_true"
                    verb_parser.add_argument(arg_name, **kwargs)

                # Set the method to call for this subcommand
                verb_parser.set_defaults(func=obj)

    return parser

def main():
    # --- Determine the modules directory ---
    # Option 1: Use the first argument as the project name (passed by the wrapper)
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        project_name = sys.argv[1]
        modules_dir = Path(__file__).parent.parent / project_name / "modules"
        sys.argv = sys.argv[1:]  # Remove the project name from sys.argv
    else:
        # Option 2: Fall back to a default location (e.g., same directory as cli.py)
        modules_dir = Path(__file__).parent / "modules"

    # Ensure the modules directory exists
    if not modules_dir.exists():
        print(f"Error: Modules directory not found: {modules_dir}")
        sys.exit(1)

    # --- Set up and run the CLI ---
    parser = setup_cli(modules_dir)
    args = parser.parse_args()
    try:
        args.func(**vars(args))
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
