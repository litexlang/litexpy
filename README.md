# litexpy

Python runner for an interactive `litex` terminal session.

## Links

- PyPI: https://pypi.org/project/litexpy/
- GitHub: https://github.com/litexlang/litexpy

## Prerequisites

`litexpy` requires the `litex` command to be available in your terminal.

To install `litex` locally, see the Litex setup guide:
https://litexlang.com/doc/Setup

## Usage

```python
import litexpy

runner = litexpy.Runner()

results = runner.run("1 = 1\n0 = 0")
clear_result = runner.clear()
runner.quit()
```

`litexpy.Runner()` starts the `litex` command in an interactive terminal
process. `run(script)` sends script to that process and returns the JSON
results as a list of Python `dict` objects, `clear()` is equivalent to
`run("clear")`, and `quit()` closes the running `litex` process.
