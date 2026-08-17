# 🌿 SubParsley
> **A lightweight, extensible, and reusable CLI framework for Python projects**

This framework allows you to dynamically register commands as **verb-noun pairs** (e.g., `finj trade add`) by scanning Python modules in a project-specific `modules/` directory. It uses `argparse` subparsers for automatic command wiring and argument parsing.

---

## **Features**
- ✅ **Reusable**: Use the same `SubParsley.py` across multiple projects (e.g., `finj`).
- ✅ **Dynamic Module Loading**: Automatically loads modules from a project-specific `modules/` directory.
- ✅ **Automatic Command Wiring**: Commands are auto-registered based on Python modules and methods.
- ✅ **Self-Documenting**: Auto-generates help messages from docstrings.
- ✅ **Extensible**: Add new commands by simply adding methods to modules.

---

## **Project Structure**

```
SubParsley/
└── SubParsley.py            # Shared CLI dispatcher

<project_name>_project/
├── <project_name>           # Wrapper script (e.g., finj)
└── modules/                 # Project-specific modules
├── trade.py                 # Example module
├── portfolio.py
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
Create a `modules/` directory in your project and add Python modules (e.g., `trade.py`, `portfolio.py`).
Each module defines **commands** (methods) for its **noun** (module name).

#### Example: `modules/trade.py`
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

#### Example: `modules/portfolio.py`
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

#### **Add a new module** (e.g., `modules/inbox.py`):
```python
def process():
    """
    # @desc: Process all messages in the inbox.
    """
    print("Processing inbox...")
```

Now `./finj inbox process` will work automatically.


#### **Add a new method to an existing module** (e.g., `modules/trade.py`):
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

### **Change the Modules Directory**
By default, `SubParsley.py` looks for modules in `<project_root>/modules/`.
To use a custom directory, modify the wrapper script to pass the correct path:
```bash
python3 /path/to/shared/SubParsley.py finj --modules-dir /custom/path "\$@"
```

Then update `SubParsley.py` to handle the `--modules-dir` argument.


## Troubleshooting

- **Error: Modules directory not found**:
Ensure the `modules/` directory exists in your project and the wrapper script passes the correct project name.

- **Error: Unknown command**:
Check that the module and method names are correct and that the module is in the `modules/` directory.

- **Error: Missing arguments**:
Ensure required arguments are provided. Use `--help` to see the expected arguments for a command.


## License
This project is open-source and available under the [MIT License](LICENSE).

