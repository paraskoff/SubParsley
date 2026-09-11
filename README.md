# 🌿 SubParsley
> **A lightweight, extensible, and reusable CLI framework for Python projects**

This framework allows you to dynamically register commands as **verb-noun pairs** (e.g., `finj trade add`) by scanning the Python modules under the project directory named by `$PROJECT_DIR`. It uses `argparse` subparsers for automatic command wiring and argument parsing.

---

## **Features**
- ✅ **Reusable**: Use the same `SubParsley.py` across multiple projects (e.g., `finj`).
- ✅ **Dynamic Module Loading**: Recursively loads modules from `$PROJECT_DIR`, skipping test files.
- ✅ **Automatic Command Wiring**: Commands are auto-registered based on Python modules and methods.
- ✅ **Self-Documenting**: Auto-generates help messages from docstrings.
- ✅ **Extensible**: Add new commands by simply adding methods to modules.

---

## **Project Structure**

```
SubParsley/
└── SubParsley.py            # Shared CLI dispatcher

<project_name>_project/          # this whole directory is $PROJECT_DIR
├── <project_name>               # Wrapper script (e.g., finj)
├── trade.py                     # Example module — dispatchers live at the ROOT
├── portfolio.py
└── views/                       # Subpackages are recursed into if they
    ├── __init__.py              #   contain an __init__.py
    └── ...
```

---

## **Setup Instructions**

### 1. **Shared `SubParsley.py`**
Place `SubParsley.py` in a shared location (e.g., `~/shared/SubParsley.py` or a Git submodule).
No additional dependencies are required — it uses only Python's built-in `argparse` and `pathlib`.

---

### 2. **Project-Specific Wrapper Script**
Create a wrapper script (e.g., `finj`) in your project's root directory.
This script passes the **project name** as the first argument to `SubParsley.py`.

#### Example: `finj` (for `finj_project/`)
```bash
#!/bin/bash
export PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PROJECT_NAME="finj"
export PROJECT_DESC="Offline Financial Journal"
python3 /path/to/shared/SubParsley.py "$@"
```
Make it executable:
```bash
chmod +x finj
```

### 3. Project-Specific Modules
Add Python modules at the root of your project directory (e.g., `trade.py`, `portfolio.py`). Subdirectories containing an `__init__.py` are recursed into.
Each module defines **commands** (methods) for its **noun** (module name).

#### Example: `trade.py`
```python
def add(symbol: str, quantity: int, price: float = 0.0):
    """
    # @desc: Add a new trade to the system.
    # @arg: symbol The stock symbol (e.g., AAPL).
    # @arg: quantity Number of shares to add.
    # @arg: price Price per share (default: 0.0).
    """
    print(f"Adding trade: {symbol} (qty: {quantity}, price: {price})")

def close(trade_id: str, force: bool = False):
    """
    # @desc: Close an open trade by ID.
    # @arg: trade_id ID of the trade to close.
    # @arg: force Force close (default: False).
    """
    if force:
        print(f"Forcibly closing trade: {trade_id}")
    else:
        print(f"Closing trade: {trade_id}")
```

#### Example: `portfolio.py`
```python
def sync():
    """
    # @desc: Sync the portfolio with the server.
    """
    print("Syncing portfolio...")

def list():
    """
    # @desc: List all assets in the portfolio.
    """
    print("Listing portfolio assets...")
```


## **Docstring Annotations**
Use the following annotations in your method docstrings to customize the CLI:
|Annotation|Purpose|Example|
|---|---|---|
| `# @ns:` | Command namespace | `# @ns: portfolio` |
| `# @desc:` | Command description | `# @desc: Add a new trade to the system.` |
| `# @arg:` | Argument help text | `# @arg: symbol The stock symbol (e.g., AAPL).` |
| `# !@desc:` | Suppress the method from the CLI entirely | `# !@desc:` (on its own line, anywhere in the docstring) |

A tag is matched as a **substring anywhere in the line** — not just at the start
— so a docstring paragraph that happens to mention `@desc:` in prose is parsed
as an annotation too. Keep tag lines on their own line.

The leading `#` shown above is a convention, not a requirement: `@ns:`,
`@desc:` and `@arg:` are recognized with or without it, since the parser only
checks for the substring.

## **Behavior consumers must design around**

These are load-bearing facts about how SubParsley turns a function signature
into a CLI. They are not obvious from the annotation table above, and a
consumer that assumes otherwise will design something that breaks.

- **Type annotations drive real argparse behavior, not just help text.**
  `int` and `float` parameters get an argparse `type=` converter, so
  `shares: float` means a non-numeric `--shares` value is rejected before your
  function ever runs. `bool` parameters become `argparse.BooleanOptionalAction`,
  giving both `--flag` and `--no-flag` regardless of the parameter's default.
  A consumer that re-validates or re-converts these itself is doing
  redundant work — the value SubParsley hands your function is already the
  right type.
- **Every parameter is a single, optional, scalar flag.** There are no
  positional arguments, no `nargs`, and no `action="append"`. A repeatable or
  list-valued argument (`--tag foo --tag bar`) **cannot be expressed** — model
  it instead as one delimited string (`--tags "foo,bar"`) or a path to a file,
  and parse that yourself.
- **Short flags are derived from parameter names, and order matters.**
  `generate_unique_short_name` takes the first letter of each word in the
  parameter name (`spec_path` → `sp`), and on a collision walks progressively
  longer prefixes of the *next* parameter that collided. Collisions are
  resolved **per verb**, not across the whole CLI, but within one verb the
  **declaration order of your parameters decides which one keeps the short
  form** — reordering a signature can silently change `-s` from meaning
  `sector` to meaning `status`.
- **A missing or malformed argument now exits 1 with `Error: ...`**, the same
  convention every other failure in a SubParsley-based CLI uses — not
  argparse's own usage banner and exit code 2. This is implemented by
  `DyingArgumentParser`, which raises `ArgumentError` from `error()` instead of
  calling `sys.exit()` directly; `main()` catches it alongside every other
  exception.
- **A colon in `@desc:`/`@arg:`/`@ns:` text is now legal.** Tag text used to be
  taken as `line.split(":")[1]`, so `@desc: Render a note: fill placeholders`
  silently lost everything after the second colon. It is now
  `line.split(":", 1)`, so a colon anywhere in the description or an argument's
  help text survives.
- **Modules are auto-discovered, and the discovery rule is easy to trip on.**
  `load_modules_recursive` imports every `*.py` directly in the project
  directory, then recurses into a subdirectory **only if it contains an
  `__init__.py` and its name does not start with `_`**. A new subpackage with
  no `__init__.py` registers nothing, silently. A module that raises on import
  is skipped with a `Warning: skipping module '<name>': <Type>: <message>` on
  **stderr**, and the CLI continues without it. Set `SUBPARSLEY_DEBUG=1` to
  re-raise instead of skipping.
- **Test modules are never imported.** `*_test*.py`, `tests.py`, `conftest.py`
  and `setup.py` are skipped by default, in both file and directory position.
  They contribute no verbs, and importing them on every CLI invocation was pure
  startup cost — 45% of kolobar's `.py` files, plus `unittest` itself. Add more
  patterns with `$PROJECT_IGNORE`.
- **Only the project root goes on `sys.path`.** Modules are imported by their
  dotted package name. Two modules with the same base name at different depths
  (`schema.py`, `models/schema.py`) therefore both load correctly and neither
  shadows the other.
- **Errors go to stderr and exit 1.** `Error: ...` is written to stderr, so
  `VALUE=$(yourcli something)` captures data only, and `2>/dev/null` actually
  silences complaints. The prefix and the exit code are unchanged from earlier
  versions; only the stream differs.
- **`-h` is reserved.** A parameter whose initials would produce `h` simply
  gets no short flag, because claiming `-h` raises at parser-construction time
  and would take down the whole CLI. Any other short-flag conflict degrades the
  same way, with a warning.
- **A `%` in tag text is safe.** Help strings are `%`-escaped before argparse
  sees them, so `@desc: adds up to 100%` renders rather than raising
  `unsupported format character`. A side effect is that argparse's own
  `%(default)s` interpolation is not available in docstring text.


### Usage Examples

**List Available Commands**
```bash
./finj --help
```

Output:
```text
usage: SubParsley.py finj [-h] {trade,portfolio} ...

positional arguments:
  {trade,portfolio}  Nouns
    trade           Commands for trade
    portfolio       Commands for portfolio

optional arguments:
  -h, --help         show this help message and exit
```


**List Verbs for a Noun**
```bash
./finj trade --help
```

Output:
```text
usage: SubParsley.py finj trade [-h] {add,close} ...

positional arguments:
  {add,close}  Verbs
    add        Add a new trade to the system.
    close      Close an open trade by ID.

optional arguments:
  -h, --help   show this help message and exit
```


**Run a Command**
```bash
./finj trade add --symbol AAPL --quantity 10 --price 150.25
```

Output:
```text
Adding trade: AAPL (qty: 10, price: 150.25)
```


**Run a Command with Flags**
```bash
./finj trade close --trade-id 12345 --force
```

Output:
```text
Forcibly closing trade: 12345
```


### Adding New Commands

#### **Add a new module** (e.g., `inbox.py`):
```python
def process():
    """
    # @desc: Process all messages in the inbox.
    """
    print("Processing inbox...")
```

Now `./finj inbox process` will work automatically.


#### **Add a new method to an existing module** (e.g., `trade.py`):
```python
def update(trade_id: str, quantity: int):
    """
    # @desc: Update the quantity of a trade.
    # @arg: trade_id ID of the trade to update.
    # @arg: quantity New quantity.
    """
    print(f"Updating trade {trade_id} to quantity: {quantity}")
```

Now `./finj trade update --trade-id 12345 --quantity 20` will work.


## Customization

### **Environment contract**
The wrapper script configures SubParsley entirely through the environment;
there are no framework-level command-line flags.

| Variable | Meaning |
|---|---|
| `PROJECT_DIR` | Directory to scan for dispatcher modules. Defaults to SubParsley's own directory. |
| `PROJECT_NAME` | Program name shown in usage. |
| `PROJECT_DESC` | One-line description shown in `--help`. |
| `PROJECT_IGNORE` | Extra comma/semicolon-separated fnmatch patterns to skip, **added to** the defaults. |
| `PROJECT_IGNORE_DEFAULTS` | Set to `0` to drop the built-in ignore patterns. Rarely what you want. |
| `SUBPARSLEY_DEBUG` | Print tracebacks and re-raise import failures. `0`/`false`/`no` count as off. |


## Troubleshooting

- **Error: Project directory not found**:
Ensure `$PROJECT_DIR` points at an existing directory.

- **A command you just added does not appear**: its module probably failed to
import. SubParsley prints `Warning: skipping module '<name>': ...` to stderr
and carries on. Set `SUBPARSLEY_DEBUG=1` to get the traceback instead.

- **Error: Unknown command**:
Check that the module and method names are correct and that the module is inside `$PROJECT_DIR` (and, if nested, that every parent directory has an `__init__.py`).

- **Error: Missing arguments**:
Ensure required arguments are provided. Use `--help` to see the expected arguments for a command.

- **A bad value exits with `Error: ...` and status 1** (not argparse's own usage
  banner and exit code 2): this is deliberate, so scripts driving a
  SubParsley-based CLI can check `$?` the same way for every kind of failure.


## License
This project is open-source and available under the [MIT License](LICENSE).

