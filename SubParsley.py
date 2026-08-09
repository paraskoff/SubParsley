#!/usr/bin/env python3
""" SubParsley 
    A lightweight, extensible, and reusable CLI framework for Python projects 
"""

import os
import importlib
import inspect
import sys
import argparse
from pathlib import Path

def setup_cli(modules_dir: Path, name: str = "SubParsley", desc: str = "SubParsley - Extensible CLI Tool"):
    # Main parser
    parser = argparse.ArgumentParser(prog=name, description=desc)
    subparsers = parser.add_subparsers(dest="noun", title="Nouns", required=True)

    # Load all modules in the specified modules_dir
    sys.path.insert(0, str(modules_dir))

    # Dictionary to collect verbs for each module
    module_verbs = {}

    for module_file in modules_dir.glob("*.py"):
        if module_file.name == "__init__.py":
            continue
        module_name = module_file.stem
        try:
            module = importlib.import_module(module_name)
        except:
            continue

        # Collect all valid verbs for this module
        verbs = []
        for name, obj in inspect.getmembers(module):
            if inspect.isfunction(obj) and not name.startswith("_"):
                doc = inspect.getdoc(obj) or ""
                if "@desc:" in doc and "!@desc:" not in doc:
                    verbs.append((name, obj))

        if verbs:  # Only add module if it has verbs
            module_verbs[module_name] = (module, verbs)

    # Create subparsers for modules that have verbs
    for module_name, (module, verbs) in module_verbs.items():
        noun_parser = subparsers.add_parser(
            module_name,
            help=f"Commands for {module_name}",
        )
        noun_subparsers = noun_parser.add_subparsers(
            dest="verb",
            title="Verbs",
            required=True,
        )

        for name, obj in verbs:
            # Extract metadata from docstring
            doc = inspect.getdoc(obj) or ""
            desc = None
            arg_help = {}
            for line in doc.split("\n"):
                line = line.strip()
                if "!@desc:" in line:
                    continue
                if "@desc:" in line:
                    desc = line.split(":")[1].strip()
                if "@arg:" in line:
                    parts = line.split(":")[1].strip().split(" ")
                    param_name = parts[0]
                    help_text = " ".join(parts[1:])
                    arg_help[param_name] = help_text

            if desc:
                verb_parser = noun_subparsers.add_parser(
                    name,
                    help=desc or f"{name} {module_name}",
                    description=desc,
                )

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
                    else:
                        kwargs["required"] = True
                    if param.annotation is not inspect.Parameter.empty:
                        if param.annotation == int:
                            kwargs["type"] = int
                        elif param.annotation == float:
                            kwargs["type"] = float
                        elif param.annotation == bool:
                            kwargs["action"] = "store_true"
                    verb_parser.add_argument(arg_name, **kwargs)

                verb_parser.set_defaults(func=obj)

    return parser

def main():
    # --- Determine the modules directory ---
    project_dir = Path(os.environ.get('PROJECT_DIR', '')) or Path(__file__).parent
    project_name = os.environ.get('PROJECT_NAME', "SubParsley")
    project_desc = os.environ.get('PROJECT_DESC', "SubParsley - Extensible CLI Tool")
        
    # Ensure the modules directory exists
    if not project_dir.exists():
        print(f"Error: Project directory not found: {project_dir}")
        sys.exit(1)

    # --- Set up and run the CLI ---
    parser = setup_cli(project_dir, project_name, project_desc)
    args = parser.parse_args()
    try:
        # Filter out 'noun' and 'verb' from args before passing to the function
        # These are used for CLI routing, not as function arguments
        func_args = {k: v for k, v in vars(args).items() if k not in ('noun', 'verb', 'func')}
        args.func(**func_args)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
