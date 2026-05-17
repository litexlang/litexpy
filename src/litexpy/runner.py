"""Runner for interactive litex sessions."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence


class Runner:
    """Run commands inside an interactive ``litex`` process."""

    def __init__(self, command: str | Sequence[str] = "litex") -> None:
        if isinstance(command, str):
            args = [command]
        else:
            args = list(command)

        self._process = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            text=True,
        )

    def run(self, script: str) -> None:
        """Send a script line to the running litex process."""
        if self._process.poll() is not None:
            raise RuntimeError("litex process is not running")
        if self._process.stdin is None:
            raise RuntimeError("litex process stdin is not available")

        self._process.stdin.write(f"{script}\n")
        self._process.stdin.flush()

    def clear(self) -> None:
        """Clear the litex terminal session."""
        self.run("clear")

    def quit(self) -> None:
        """Stop the running litex process."""
        if self._process.poll() is not None:
            return

        if self._process.stdin is not None:
            self._process.stdin.close()

        try:
            self._process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()


def runner() -> Runner:
    """Create a litex runner."""
    return Runner()
