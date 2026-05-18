"""Runner for interactive litex sessions."""

from __future__ import annotations

import subprocess
import threading
import time
from collections.abc import Sequence
from json import JSONDecoder
from queue import Empty, Queue
from typing import Any


class Runner:
    """Run commands inside an interactive ``litex`` process."""

    def __init__(self, command: str | Sequence[str] = "litex") -> None:
        if isinstance(command, str):
            args = [command]
        else:
            args = list(command)

        self._output: Queue[str | None] = Queue()
        self._process = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self._reader = threading.Thread(target=self._read_output, daemon=True)
        self._reader.start()
        self._read_until_prompts(count=1, timeout=5)

    def run(self, script: str) -> list[dict[str, Any]]:
        """Send script to litex and return its JSON results."""
        if self._process.poll() is not None:
            raise RuntimeError("litex process is not running")
        if self._process.stdin is None:
            raise RuntimeError("litex process stdin is not available")

        self._process.stdin.write(f"{script}\n")
        self._process.stdin.flush()
        output = self._read_until_prompts(count=self._prompt_count(script), timeout=30)
        return self._parse_json_results(output)

    def clear(self) -> list[dict[str, Any]]:
        """Clear the litex terminal session."""
        return self.run("clear")

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

    def _read_output(self) -> None:
        if self._process.stdout is None:
            self._output.put(None)
            return

        while True:
            chunk = self._process.stdout.read(1)
            if chunk == "":
                self._output.put(None)
                return
            self._output.put(chunk)

    def _read_until_prompts(self, count: int, timeout: float) -> str:
        deadline = time.monotonic() + timeout
        output = ""
        prompt_count = 0

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("timed out waiting for litex output")

            try:
                chunk = self._output.get(timeout=remaining)
            except Empty as exc:
                raise TimeoutError("timed out waiting for litex output") from exc

            if chunk is None:
                if self._process.poll() is None:
                    continue
                raise RuntimeError("litex process closed before returning a prompt")

            output += chunk
            if output.endswith(">>> "):
                prompt_count += 1
                if prompt_count >= count:
                    return output

    def _parse_json_results(self, output: str) -> list[dict[str, Any]]:
        decoder = JSONDecoder()
        results: list[dict[str, Any]] = []
        index = 0

        while index < len(output):
            if output[index] != "{":
                index += 1
                continue

            try:
                value, offset = decoder.raw_decode(output[index:])
            except ValueError:
                index += 1
                continue

            if isinstance(value, dict):
                results.append(value)
                index += offset
                continue

            index += 1

        if results:
            return results

        raise ValueError(f"litex output did not contain JSON objects: {output!r}")

    def _prompt_count(self, script: str) -> int:
        return max(1, sum(1 for line in script.splitlines() if line.strip()))


def runner() -> Runner:
    """Create a litex runner."""
    return Runner()
