#!/usr/bin/env python3
""" SubParsley
    A lightweight, extensible, and reusable CLI framework for Python projects
    with support for custom noun namespaces via @ns: comment annotation.
"""

import os
import importlib
import inspect
import sys
import argparse
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any, Callable, Set

def load_modules_recursive(modules_dir: Path, parent_module: str = "") -> List[Tuple[str, Any]]:
    """
    Recursively load all Python modules from the specified directory and its subdirectories.

    Args:
        modules_dir: Path to the directory containing module files
        parent_module: Parent module name for nested modules (e.g., "subdir" for "subdir.module")

    Returns:
        List of tuples containing (module_name, module_object) for successfully loaded modules
    """
    sys.path.insert(0, str(modules_dir))
    modules = []

    # Load modules from current directory
    for module_file in modules_dir.glob("*.py"):
        if module_file.name == "__init__.py":
            continue
        module_name = module_file.stem
        # Use parent_module prefix for nested modules
        full_module_name = f"{parent_module}.{module_name}" if parent_module else module_name
        try:
            module = importlib.import_module(full_module_name)
            modules.append((full_module_name, module))
        except Exception as e:
            print(e)
            continue

    # Recursively load modules from subdirectories
    for subdir in modules_dir.iterdir():
        if subdir.is_dir() and not subdir.name.startswith("_"):
            init_file = subdir / "__init__.py"
            if init_file.exists():
                sub_module_name = subdir.name
                full_parent = f"{parent_module}.{sub_module_name}" if parent_module else sub_module_name
                submodules = load_modules_recursive(subdir, full_parent)
                modules.extend(submodules)

    return modules

def extract_function_metadata(func: Callable) -> Tuple[Optional[str], Dict[str, str], Optional[str]]:
    """
    Extract description, argument help, and custom namespace from a function's docstring.

    Args:
        func: The function to extract metadata from

    Returns:
        Tuple of (description, arg_help_dict, namespace) where:
        - description: The description text from @desc: annotation, or None
        - arg_help_dict: Dictionary mapping parameter names to help text from @arg: annotations
        - namespace: The custom namespace from @ns: annotation, or None
    """
    doc = inspect.getdoc(func) or ""
    desc = None
    arg_help = {}
    namespace = None

    for line in doc.split("\n"):
        line = line.strip()
        if "!@desc:" in line:
            # Skip methods annotated with `!@`
            desc = None
            break
        if "@desc:" in line:
            desc = line.split(":")[1].strip()
        if "@arg:" in line:
            parts = line.split(":")[1].strip().split(" ")
            param_name = parts[0]
            help_text = " ".join(parts[1:])
            arg_help[param_name] = help_text
        if "@ns:" in line:
            namespace = line.split(":")[1].strip()

    return desc, arg_help, namespace

def generate_base_short_name(param_name: str) -> str:
    """
    Generate a base short name from a parameter name.

    Takes the first letter of each word in a snake_case or camelCase parameter name.

    Args:
        param_name: The parameter name (e.g., 'spec_path' or 'specPath')

    Returns:
        A base short name (e.g., 'sp' for 'spec_path')
    """
    if not param_name:
        return ""

    # Split by underscores or camelCase
    parts = []
    current_part = param_name[0]
    for char in param_name[1:]:
        if char == '_' or char.isupper():
            if current_part:
                parts.append(current_part)
            current_part = char.lower() if char != '_' else ''
        else:
            current_part += char
    if current_part:
        parts.append(current_part)

    # Take first character of each part
    if parts:
        return ''.join([p[0] for p in parts if p])

    return ""

def generate_unique_short_name(param_name: str, used_short_names: Set[str]) -> Optional[str]:
    """
    Generate a unique short argument name from a parameter name.

    If the base short name is already used, appends additional characters until unique.

    Args:
        param_name: The parameter name (e.g., 'spec_path' or 'spec_dir')
        used_short_names: Set of already used short names

    Returns:
        A unique short name, or None if no valid short name can be generated
    """
    base = generate_base_short_name(param_name)
    if not base:
        return None

    # If base is unique, use it
    if base not in used_short_names:
        used_short_names.add(base)
        return base

    # If not unique, try adding more characters from the parameter name
    clean_name = param_name.replace('_', '')

    # Try progressively longer prefixes
    for length in range(2, len(clean_name) + 1):
        candidate = clean_name[:length]
        if candidate not in used_short_names:
            used_short_names.add(candidate)
            return candidate

    # If all else fails, use the full clean name
    if clean_name not in used_short_names:
        used_short_names.add(clean_name)
        return clean_name

    return None

def get_valid_verbs(
    module: Any,
    default_namespace: str
) -> List[Tuple[str, Callable, Optional[str], Dict[str, str], str]]:
    """
    Get all valid verb functions from a module with their effective namespace.

    Args:
        module: The module to scan for verb functions
        default_namespace: The default namespace (module name) to use if @ns: is not specified

    Returns:
        List of tuples containing (function_name, function_object, description, arg_help, effective_namespace)
    """
    verbs = []

    for name, obj in inspect.getmembers(module):
        if inspect.isfunction(obj) and not name.startswith("_"):
            desc, arg_help, custom_ns = extract_function_metadata(obj)
            if desc:
                # Use custom namespace from @ns: annotation, or fall back to default
                effective_ns = custom_ns if custom_ns else default_namespace
                verbs.append((name, obj, desc, arg_help, effective_ns))

    return verbs

def create_verb_parser(
    noun_subparsers: Any,
    verb_name: str,
    func: Callable,
    desc: str,
    arg_help: Dict[str, str],
    module_name: str
) -> Any:
    """
    Create a verb subparser with all its arguments.

    Args:
        noun_subparsers: The subparsers object for the noun
        verb_name: Name of the verb (command)
        func: The function to call when this verb is invoked
        desc: Description for the verb
        arg_help: Dictionary of argument help texts
        module_name: Name of the parent module (noun)

    Returns:
        The configured verb parser
    """
    verb_parser = noun_subparsers.add_parser(
        verb_name,
        help=desc or f"{verb_name} {module_name}",
        description=desc,
    )

    # Add arguments based on the function signature
    sig = inspect.signature(func)
    used_short_names: Set[str] = set()

    for param_name, param in sig.parameters.items():
        if param_name == "self":
            continue

        long_name = f"--{param_name.replace('_', '-')}"
        short_name = generate_unique_short_name(param_name, used_short_names)

        kwargs = {
            "dest": param_name,
            "help": arg_help.get(param_name, f"{param_name} for {module_name}"),
        }

        if param.default is not inspect.Parameter.empty:
            kwargs["default"] = param.default
        else:
            kwargs["required"] = True

        if param.annotation is not inspect.Parameter.empty:
            type_converter = _get_type_converter(param.annotation)
            if type_converter:
                kwargs["type"] = type_converter
            elif param.annotation == bool:
                # For boolean flags, use store_true action
                kwargs["action"] = "store_true"

        # Add both short and long argument names
        if short_name:
            verb_parser.add_argument(f"-{short_name}", long_name, **kwargs)
        else:
            verb_parser.add_argument(long_name, **kwargs)

    # Set the method to call for this subcommand
    verb_parser.set_defaults(func=func)

    return verb_parser

def _get_type_converter(annotation: type) -> Optional[Callable]:
    """
    Get the appropriate type converter for argparse based on parameter annotation.

    Args:
        annotation: The type annotation from the function parameter

    Returns:
        The appropriate type converter function, or None if no conversion needed
    """
    if annotation == int:
        return int
    elif annotation == float:
        return float
    elif annotation == bool:
        return None  # bool is handled by store_true action
    return None

def create_noun_parser(
    subparsers: Any,
    noun_name: str,
    verbs: List[Tuple[str, Callable, Optional[str], Dict[str, str]]]
) -> Any:
    """
    Create a noun subparser with all its verb subcommands.

    Args:
        subparsers: The main subparsers object
        noun_name: Name of the noun (module)
        verbs: List of verb tuples from get_valid_verbs()
    """
    noun_parser = subparsers.add_parser(
        noun_name,
        help=f"Commands for {noun_name}",
    )

    noun_subparsers = noun_parser.add_subparsers(
        dest="verb",
        title="Verbs",
        required=True,
    )

    # Add all valid verbs as subcommands
    for verb_name, func, desc, arg_help in verbs:
        create_verb_parser(noun_subparsers, verb_name, func, desc, arg_help, noun_name)

    return noun_parser

def setup_cli(modules_dir: Path, name: str = "SubParsley", desc: str = "SubParsley - Extensible CLI Tool") -> Any:
    """
    Set up the CLI with all nouns and verbs from the modules directory.

    Nouns can be:
    - Explicitly set via @ns: comment annotation in function docstring
    - Default to the module name if @ns: is not used

    Multiple modules can contribute verbs to the same noun via @ns:.
    """
    # Main parser
    parser = argparse.ArgumentParser(prog=name, description=desc)
    subparsers = parser.add_subparsers(dest="noun", title="Nouns", required=True)

    # Load all modules (including from subdirectories)
    modules = load_modules_recursive(modules_dir)

    # Group verbs by their effective namespace
    # Structure: {noun_name: [(verb_name, func, desc, arg_help), ...]}
    nouns: Dict[str, List[Tuple[str, Callable, Optional[str], Dict[str, str]]]] = {}

    for module_name, module in modules:
        verbs = get_valid_verbs(module, module_name)
        for verb_name, func, verb_desc, arg_help, effective_ns in verbs:
            if effective_ns not in nouns:
                nouns[effective_ns] = []
            nouns[effective_ns].append((verb_name, func, verb_desc, arg_help))

    # Create noun parsers for each noun that has verbs
    for noun_name, noun_verbs in nouns.items():
        create_noun_parser(subparsers, noun_name, noun_verbs)

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
