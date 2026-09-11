#!/usr/bin/env python3
""" SubParsley
    A lightweight, extensible, and reusable CLI framework for Python projects
    with support for custom noun namespaces via @ns: comment annotation.
"""

import os
import fnmatch
import importlib
import inspect
import sys
import argparse
import re
import traceback
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from types import UnionType
from typing import (Any, Callable, Dict, List, Optional, Sequence, Set, Tuple,
                    Union, get_args, get_origin)

# Never imported as dispatcher modules. Test code contributes no verbs, and in
# kolobar it is 55 of 122 .py files — 45% of every import on every CLI
# invocation, plus unittest itself, before argparse is even constructed. Worse,
# any module-level side effect in a test file would run during a user's
# ordinary command.
# `__main__.py` is not merely uninteresting, it is actively harmful:
# importlib.import_module("__main__") returns the ALREADY-RUNNING entry module —
# SubParsley itself. This module's own docstrings mention `@desc:` and `@ns:`
# while documenting them, so they parse as real annotations and SubParsley
# registers its own internals as CLI verbs. Found when a consumer added a
# `__main__.py` console-script entry point inside its package.
DEFAULT_IGNORE = ("*_test*.py", "tests.py", "conftest.py", "setup.py", "__main__.py")

IGNORE_ENV_VAR = "PROJECT_IGNORE"
IGNORE_DEFAULTS_ENV_VAR = "PROJECT_IGNORE_DEFAULTS"


def resolve_ignore_patterns() -> Tuple[str, ...]:
    """ DEFAULT_IGNORE plus anything in $PROJECT_IGNORE (comma or semicolon
        separated).

        ADDITIVE by default, and opting out of the defaults takes a separate
        explicit `PROJECT_IGNORE_DEFAULTS=0`. An accidental full override would
        silently reintroduce the very defect this exists to fix, and it costs
        latency rather than correctness — so it would never be noticed. The
        dangerous choice has to be the loud one.
    """
    extra = os.environ.get(IGNORE_ENV_VAR, "").replace(";", ",")
    patterns = [p.strip() for p in extra.split(",") if p.strip()]
    if os.environ.get(IGNORE_DEFAULTS_ENV_VAR, "").strip().lower() in _FALSEY - {""}:
        return tuple(patterns)
    return DEFAULT_IGNORE + tuple(patterns)


def _is_ignored(path: Path, root: Path, patterns: Sequence[str]) -> bool:
    """Matches the bare name AND the root-relative path, so both `*_test*.py`
       and `ext/legacy/*` work."""
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        relative = path.name
    return any(fnmatch.fnmatch(path.name, pattern) or fnmatch.fnmatch(relative, pattern)
               for pattern in patterns)


def warn_import_failure(module_name: str, exc: BaseException):
    """ Default `on_error`: name the module that failed and why.

        The previous handler was a bare `print(e)` followed by `continue`, so a
        syntax error in one dispatcher silently deleted that entire namespace
        from the CLI, leaving an unlabelled stray line as the only clue.
    """
    print(f"Warning: skipping module '{module_name}': {type(exc).__name__}: {exc}",
          file=sys.stderr)


def load_modules_recursive(modules_dir: Path, parent_module: str = "",
                           ignore: Sequence[str] = None,
                           on_error: Callable[[str, BaseException], None] = None,
                           root: Path = None) -> List[Tuple[str, Any]]:
    """
    Recursively load all Python modules from the specified directory and its subdirectories.

    Only the PROJECT ROOT goes on sys.path, once. Every module is then imported
    by the dotted name computed here. Inserting each subdirectory too (as this
    used to) is a shadowing hazard with no compensating function: kolobar has
    schema.py at five different levels, plus note/backup/template/moc/prompt
    duplicated across layers, and nothing broke only because the root modules
    happened to import first and win the sys.modules cache.

    Args:
        modules_dir: Path to the directory containing module files
        parent_module: Parent module name for nested modules (e.g., "subdir" for "subdir.module")
        ignore: fnmatch patterns to skip; defaults to resolve_ignore_patterns()
        on_error: called with (module_name, exception) when an import fails
        root: the project root, for relative-path matching and sys.path (internal)

    Returns:
        List of tuples containing (module_name, module_object) for successfully loaded modules
    """
    if ignore is None:
        ignore = resolve_ignore_patterns()
    if on_error is None:
        on_error = warn_import_failure
    if root is None:
        root = modules_dir
        # Once, at the top-level call only. Index 0 so the consumer's own
        # modules win over anything ambient.
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))

    modules = []

    # Load modules from current directory
    for module_file in sorted(modules_dir.glob("*.py")):
        if module_file.name == "__init__.py":
            continue
        if _is_ignored(module_file, root, ignore):
            continue
        module_name = module_file.stem
        # Use parent_module prefix for nested modules
        full_module_name = f"{parent_module}.{module_name}" if parent_module else module_name
        try:
            module = importlib.import_module(full_module_name)
            modules.append((full_module_name, module))
        except Exception as e:
            # Deliberately not BaseException: a module calling sys.exit() at
            # import time raises SystemExit, and swallowing that turned a hard
            # failure into a missing namespace.
            on_error(full_module_name, e)
            if debug_enabled():
                raise
            continue

    # Recursively load modules from subdirectories
    for subdir in sorted(modules_dir.iterdir()):
        if subdir.is_dir() and not subdir.name.startswith("_"):
            if _is_ignored(subdir, root, ignore):
                continue
            init_file = subdir / "__init__.py"
            if init_file.exists():
                sub_module_name = subdir.name
                full_parent = f"{parent_module}.{sub_module_name}" if parent_module else sub_module_name
                submodules = load_modules_recursive(subdir, full_parent, ignore, on_error, root)
                modules.extend(submodules)

    return modules


# A bracketed spec may follow the parameter name in an `@arg:` line:
#
#     @arg: portfolio [-p] Portfolio name
#     @arg: action [-a choices=BUY|SELL] Trade action
#     @arg: set [repeat] Placeholder value as KEY=VALUE
#
# One extended grammar rather than a family of new tags (@short:, @choices:, ...):
# it keeps the whole schema for an argument on one greppable line, needs no new
# parser entry points, and degrades survivably — an OLDER SubParsley reading a
# newer docstring renders `[-p]` as literal help text instead of crashing.
#
# The bracket is only special in FIRST position, so help text that happens to
# start with a bracket later on is untouched.
ARG_SPEC_RE = re.compile(r"^\[(?P<spec>[^\]]*)\]\s*(?P<help>.*)$", re.S)

# Pipe-separated, not comma: a choice may legitimately contain a comma.
CHOICES_SEP = "|"


@dataclass
class ArgSpec:
    """ Everything an `@arg:` line declares about one parameter.

        `help` is the only field the original grammar had; the rest default to
        "unset", so a plain `@arg: name text` behaves exactly as before.
    """
    help: str = ""
    short: Optional[str] = None
    choices: Optional[List[str]] = None
    repeat: bool = False
    nargs: Optional[str] = None

    def __str__(self) -> str:
        return self.help


def _parse_arg_spec(rest: str, on_unknown: Callable[[str], None] = None) -> ArgSpec:
    """ Split an `@arg:` line's remainder into its bracketed spec and its help.

        `rest` is everything after the parameter name. Unknown modifiers are
        reported rather than ignored — a silently-dropped `[choices=...]` would
        look like it worked.
    """
    rest = rest.strip()
    match = ARG_SPEC_RE.match(rest)
    if not match:
        return ArgSpec(help=rest)

    spec = ArgSpec(help=match.group("help").strip())
    for token in match.group("spec").split():
        if token.startswith("-") and len(token) > 1:
            spec.short = token.lstrip("-")
        elif token.startswith("choices="):
            spec.choices = [c for c in token[len("choices="):].split(CHOICES_SEP) if c]
        elif token == "repeat":
            spec.repeat = True
        elif token.startswith("nargs="):
            spec.nargs = token[len("nargs="):]
        elif on_unknown:
            on_unknown(token)
    return spec


def extract_function_metadata(func: Callable) -> Tuple[Optional[str], Dict[str, "ArgSpec"], Optional[str]]:
    """
    Extract description, argument specs, and custom namespace from a function's docstring.

    Args:
        func: The function to extract metadata from

    Returns:
        Tuple of (description, arg_spec_dict, namespace) where:
        - description: The description text from @desc: annotation, or None
        - arg_spec_dict: Dictionary mapping parameter names to their ArgSpec
        - namespace: The custom namespace from @ns: annotation, or None
    """
    doc = inspect.getdoc(func) or ""
    desc = None
    arg_help: Dict[str, ArgSpec] = {}
    namespace = None

    def unknown(token, param=None):
        print(f"Warning: {func.__module__}.{func.__name__} @arg: {param}: "
              f"unknown modifier {token!r}", file=sys.stderr)
        if debug_enabled():
            raise ValueError(f"unknown @arg modifier {token!r} on {func.__name__}")

    for line in doc.split("\n"):
        line = line.strip()
        if "!@desc:" in line:
            # Skip methods annotated with `!@`
            desc = None
            break
        if "@desc:" in line:
            # split(":", 1): a colon inside the description text itself must
            # survive. A plain split(":") silently drops everything after the
            # SECOND colon, e.g. "@desc: Render a note: fill placeholders" was
            # truncated to "Render a note".
            desc = line.split(":", 1)[1].strip()
        if "@arg:" in line:
            parts = line.split(":", 1)[1].strip().split(" ", 1)
            param_name = parts[0]
            rest = parts[1] if len(parts) > 1 else ""
            arg_help[param_name] = _parse_arg_spec(
                rest, on_unknown=lambda t, p=param_name: unknown(t, p))
        if "@ns:" in line:
            namespace = line.split(":", 1)[1].strip()

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

# argparse registers -h itself, and add_argument("-h", ...) raises at PARSER
# CONSTRUCTION time — so a consumer parameter whose initials produce "h"
# (host, hours, header) would take down the entire CLI, not just one verb.
# No current kolobar parameter produces it, which makes reserving it free.
RESERVED_SHORT_NAMES = frozenset({"h"})

SHORT_FLAGS_ENV_VAR = "PROJECT_SHORT_FLAGS"


def _short_flags_mode() -> str:
    """ "auto" (default) derives a short flag for every parameter, honouring any
        explicit `[-x]`. "explicit" derives nothing — a parameter gets the short
        flag it declares, or none.

        Opt-in, because switching to "explicit" silently removes flags a
        consumer's users may already have scripted against. The intended
        migration is: annotate every verb with the flag it ALREADY derives, add
        a test pinning the map, and only then switch.
    """
    mode = os.environ.get(SHORT_FLAGS_ENV_VAR, "auto").strip().lower()
    return mode if mode in ("auto", "explicit") else "auto"


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
        # `obj.__module__ == module.__name__` keeps a RE-IMPORTED function from
        # registering a second time: `from helpers import render`, where render
        # carries @desc:, would otherwise publish a phantom verb in the
        # importing module's namespace too. kolobar has zero such cases today
        # (36 generated verbs == 36 local defs), so this is free hardening.
        if (inspect.isfunction(obj) and not name.startswith("_")
                and obj.__module__ == module.__name__):
            desc, arg_help, custom_ns = extract_function_metadata(obj)
            if desc:
                # Use custom namespace from @ns: annotation, or fall back to default
                effective_ns = custom_ns if custom_ns else default_namespace
                verbs.append((name, obj, desc, arg_help, effective_ns))

    return verbs

def escape_help(text: str) -> str:
    """ Escape `%` for argparse's help formatter.

        argparse %-expands the `help=` string when it renders it, so a single
        `%` in consumer-supplied text raises at FORMAT time and takes down the
        whole namespace's help. kolobar's
        `@desc: ...adds up to 100% with no over-allocated sleeve` made
        `klbr allocation --help` die with

            unsupported format character 'w' (0x77) at index 49

        and rendered all five of that noun's verbs undiscoverable. The same
        applies to `@arg:` text, which fails differently and even less legibly
        (`TypeError: %d format: a real number is required, not dict`).

        Deliberately NOT applied to `description=`, which argparse does not
        expand — escaping there would print a literal `100%%` to the user.

        A consequence worth stating: this also neutralises argparse's own
        interpolation vocabulary (`%(default)s`). That is intended. A docstring
        is prose written by a consumer, not a format string, and reaching
        argparse internals through it by accident is the bug, not a feature.
    """
    return text.replace("%", "%%") if text else text


def create_verb_parser(
    noun_subparsers: Any,
    verb_name: str,
    func: Callable,
    desc: str,
    arg_help: Dict[str, "ArgSpec"],
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
        help=escape_help(desc or f"{verb_name} {module_name}"),
        description=desc,
    )

    # Add arguments based on the function signature
    sig = inspect.signature(func)
    used_short_names: Set[str] = set(RESERVED_SHORT_NAMES)

    # Claim every EXPLICIT short flag up front. Derivation walks parameters in
    # declaration order and takes the first free initial, so a derived flag
    # could otherwise steal a letter that a later parameter had annotated —
    # which is exactly the order-dependence explicit flags exist to remove.
    explicit: Dict[str, str] = {}
    for name, spec in (arg_help or {}).items():
        if getattr(spec, "short", None):
            if spec.short in explicit.values():
                fail(f"{module_name} {verb_name}: two parameters both declare "
                     f"-{spec.short}")
            explicit[name] = spec.short
            used_short_names.add(spec.short)

    for param_name, param in sig.parameters.items():
        if param_name == "self":
            continue

        long_name = f"--{param_name.replace('_', '-')}"
        spec = (arg_help or {}).get(param_name)
        # Tolerate the pre-ArgSpec contract, where arg_help mapped a name to a
        # bare help string. extract_function_metadata never produces that now,
        # but a caller assembling arg_help by hand reasonably might.
        if isinstance(spec, str):
            spec = ArgSpec(help=spec)
        if param_name in explicit:
            short_name = explicit[param_name]
        elif _short_flags_mode() == "explicit":
            # Nothing is derived: a parameter has the short flag it declares, or
            # none. Opt-in, because turning derivation off silently removes
            # flags a consumer's users may have scripted against.
            short_name = None
        else:
            short_name = generate_unique_short_name(param_name, used_short_names)

        help_text = spec.help if spec is not None and spec.help else None
        kwargs = {
            "dest": param_name,
            "help": escape_help(help_text or f"{param_name} for {module_name}"),
        }
        if spec is not None:
            if spec.repeat and spec.nargs:
                fail(f"{module_name} {verb_name} --{param_name}: `repeat` and "
                     f"`nargs` cannot be combined")
            if spec.repeat:
                kwargs["action"] = "append"
            if spec.nargs:
                kwargs["nargs"] = int(spec.nargs) if spec.nargs.isdigit() else spec.nargs
            if spec.choices:
                kwargs["choices"] = spec.choices

        if param.default is not inspect.Parameter.empty:
            # A repeated flag collects into a list, so an unset one must be an
            # empty list rather than the scalar default the signature declares.
            # Built here, per parser, so two parsers never share one mutable.
            kwargs["default"] = ([] if kwargs.get("action") == "append"
                                 and param.default in (None, "")
                                 else param.default)
        else:
            kwargs["required"] = True

        if param.annotation is not inspect.Parameter.empty:
            type_converter = _get_type_converter(param.annotation)
            if type_converter:
                kwargs["type"] = type_converter
                unwrapped = _unwrap_optional(param.annotation)
                if (isinstance(unwrapped, type) and issubclass(unwrapped, Enum)
                        and not kwargs.get("choices")):
                    # Show the accepted values in --help. metavar rather than
                    # choices=: argparse would compare the CONVERTED value
                    # (a member) against the strings and reject everything.
                    kwargs["metavar"] = "{" + ",".join(enum_choices(unwrapped)) + "}"
                if kwargs.get("choices"):
                    # argparse compares the CONVERTED value against choices, so
                    # `choices=1|2` on an int parameter must hold ints, not "1".
                    kwargs["choices"] = [type_converter(c) for c in kwargs["choices"]]
            elif _unwrap_optional(param.annotation) is bool:
                # BooleanOptionalAction, not store_true: store_true can only ever
                # turn a flag ON, so a bool parameter DEFAULTING TO True had no way
                # to be turned off. This gives both --flag and --no-flag.
                kwargs["action"] = argparse.BooleanOptionalAction

        if kwargs.get("choices") and "type" not in kwargs:
            # A plain str parameter with declared choices: fold case so the
            # declared spelling is what reaches the function.
            kwargs["type"] = _canonical_choice(kwargs["choices"])

        # Add both short and long argument names. A short-flag clash must
        # degrade to "no short flag", never to "no CLI": add_argument raises
        # ArgumentError at construction time, which would abort the whole
        # parser build rather than this one option.
        if short_name:
            try:
                verb_parser.add_argument(f"-{short_name}", long_name, **kwargs)
                continue
            except argparse.ArgumentError as e:
                print(f"Warning: {module_name} {verb_name}: dropping short flag "
                      f"-{short_name} for --{param_name}: {e}", file=sys.stderr)
        verb_parser.add_argument(long_name, **kwargs)

    # Set the method to call for this subcommand
    verb_parser.set_defaults(func=func)

    return verb_parser

def _decimal_arg(raw) -> Decimal:
    """ argparse `type=` converter for a Decimal parameter.

        Built from the RAW STRING argparse hands us, never via float. That is the
        entire point: a float has already destroyed information by the time you
        see it, and `--price 1234567890123456789.05` cannot be recovered from one.

        Raises ArgumentTypeError, not decimal.InvalidOperation. argparse._get_value
        catches only ArgumentTypeError, TypeError and ValueError, so an
        InvalidOperation would escape as a raw traceback instead of going through
        DyingArgumentParser -> ArgumentError -> the framework's `Error: ...` path.

        ArgumentTypeError specifically, rather than ValueError, because argparse
        uses its message verbatim. A ValueError falls back to the generic
        "invalid <converter.__name__> value: ...", which leaks the internal
        function name to the user.

        Non-finite values are rejected: `Decimal("nan")` parses happily, and
        `--shares nan` would post a NaN row that compares False against
        everything downstream, including itself.
    """
    try:
        value = Decimal(str(raw).strip())
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError(f"{raw!r} is not a decimal number") from exc
    if not value.is_finite():
        raise argparse.ArgumentTypeError(f"{raw!r} is not a finite decimal number")
    return value


def _enum_arg(enum_cls) -> Callable:
    """ argparse `type=` converter for an Enum parameter.

        Users type the VALUE (`BUY`), not the member name, because the value is
        what the domain calls it and what ends up in the data. Without this an
        Enum-annotated parameter silently arrived as a raw string, which then
        never compared equal to any member — the same class of bug as
        finj's `TxAction` comparison, which once inverted every BUY into a SELL.

        Raises ArgumentTypeError so argparse uses the message verbatim rather
        than falling back to "invalid <converter name> value".
    """
    by_value = {str(member.value): member for member in enum_cls}

    def convert(raw):
        try:
            return by_value[str(raw)]
        except KeyError:
            allowed = ", ".join(sorted(by_value))
            raise argparse.ArgumentTypeError(
                f"{raw!r} is not one of: {allowed}") from None

    convert.__name__ = enum_cls.__name__
    return convert


def enum_choices(enum_cls) -> List[str]:
    """The values an Enum parameter accepts, for `choices`/metavar display."""
    return [str(member.value) for member in enum_cls]


def _canonical_choice(choices: List[str]) -> Callable:
    """ Match a `choices=` value case-insensitively and return the declared spelling.

        argparse applies `type=` before checking `choices`, so this is where
        case-folding has to happen. It matters because every consumer parameter
        that gained `choices` was ALREADY case-insensitive — normalised with
        .upper() or .lower() somewhere downstream — and a case-sensitive
        `choices` would have silently broken `--action buy`, which worked for
        years.

        An unrecognised value is returned unchanged so argparse's own `choices`
        check produces the error, listing the valid values.
    """
    canonical = {c.casefold(): c for c in choices}

    def convert(raw):
        return canonical.get(str(raw).casefold(), raw)

    convert.__name__ = "choice"
    return convert


def _unwrap_optional(annotation):
    """ Reduce `Optional[X]` / `X | None` to `X`.

        A prerequisite, not a nicety. Consumers write `target_dir: str = None`
        today; the moment those are corrected to the accurate `Optional[str]`,
        an unwrapping-free lookup silently stops matching and `Optional[int]`
        loses its converter — turning a validated number back into a string with
        no error anywhere.
    """
    origin = get_origin(annotation)
    if origin is Union or origin is UnionType:
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def _get_type_converter(annotation: type) -> Optional[Callable]:
    """
    Get the appropriate type converter for argparse based on parameter annotation.

    Args:
        annotation: The type annotation from the function parameter

    Returns:
        The appropriate type converter function, or None if no conversion needed
    """
    annotation = _unwrap_optional(annotation)
    if annotation is int:
        return int
    elif annotation is float:
        return float
    elif annotation is Decimal:
        return _decimal_arg
    elif isinstance(annotation, type) and issubclass(annotation, Enum):
        return _enum_arg(annotation)
    elif annotation is bool:
        return None  # bool is handled by BooleanOptionalAction, not a type converter
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
        help=escape_help(f"Commands for {noun_name}"),
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

class ArgumentError(Exception):
    """Raised instead of argparse's own sys.exit(2) on a parse failure, so
    main() can report it through the same `Error: ...` / exit(1) path as every
    other failure in this framework."""


class DyingArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that raises on a parse error instead of printing argparse's
    usage text and calling sys.exit(2) directly. A bad --price value or an
    unrecognized flag used to bypass the framework's own error convention
    entirely; this routes it through the same one."""

    def error(self, message):
        raise ArgumentError(message)


def setup_cli(modules_dir: Path, name: str = "SubParsley", desc: str = "SubParsley - Extensible CLI Tool") -> Any:
    """
    Set up the CLI with all nouns and verbs from the modules directory.

    Nouns can be:
    - Explicitly set via @ns: comment annotation in function docstring
    - Default to the module name if @ns: is not used

    Multiple modules can contribute verbs to the same noun via @ns:.
    """
    # Main parser
    parser = DyingArgumentParser(prog=name, description=desc)
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

DEBUG_ENV_VAR = "SUBPARSLEY_DEBUG"
# Anything else non-empty is on. These four are spelled out because
# `SUBPARSLEY_DEBUG=0` obviously means "off" to a human, and a bare truthiness
# check would turn it on.
_FALSEY = {"", "0", "false", "no"}


def debug_enabled() -> bool:
    """Whether to surface tracebacks and re-raise swallowed import errors."""
    return os.environ.get(DEBUG_ENV_VAR, "").strip().lower() not in _FALSEY


def fail(message: str, exc: BaseException = None):
    """ Report a fatal error and exit 1.

        STDERR, not stdout: errors used to go to stdout, so
        `SBOR=$(klbr sbor show --brief)` captured error text as data and
        `klbr ... 2>/dev/null` hid nothing. The `Error: ` prefix and the exit
        code are unchanged — the stream is the only difference.

        The one-line message is printed BEFORE any traceback so the readable
        part is not buried under a stack.
    """
    print(f"Error: {message}", file=sys.stderr)
    if exc is not None and debug_enabled():
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
    sys.exit(1)


def resolve_config() -> Tuple[Path, str, str]:
    """Reads the PROJECT_* environment contract. Separated from main() so tests
       can drive main(argv=...) without reaching into os.environ."""
    project_dir = Path(os.environ.get('PROJECT_DIR', '')) or Path(__file__).parent
    project_name = os.environ.get('PROJECT_NAME', "SubParsley")
    project_desc = os.environ.get('PROJECT_DESC', "SubParsley - Extensible CLI Tool")
    return project_dir, project_name, project_desc


def main(argv: List[str] = None):
    project_dir, project_name, project_desc = resolve_config()

    if not project_dir.exists():
        fail(f"Project directory not found: {project_dir}")

    parser = setup_cli(project_dir, project_name, project_desc)
    try:
        # parse_args() is inside the try too: a missing/invalid argument must
        # exit 1 through this same message, not argparse's own exit(2).
        args = parser.parse_args(argv)
        # Filter out 'noun' and 'verb' from args before passing to the function
        # These are used for CLI routing, not as function arguments
        func_args = {k: v for k, v in vars(args).items() if k not in ('noun', 'verb', 'func')}
        return args.func(**func_args)
    except Exception as e:
        fail(str(e), e)


if __name__ == "__main__":
    main()
