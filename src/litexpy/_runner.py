"""Runner for interactive litex sessions."""

import os
import shlex
import subprocess
import tempfile
import threading
import time
import weakref
from json import JSONDecoder
from queue import Empty, Queue


class Runner:
    """Run commands inside an interactive ``litex`` process."""

    def __init__(self, command=None, startup_timeout=5, run_timeout=30):
        command = _resolve_command(command)
        self.command = command
        self.startup_timeout = startup_timeout
        self.run_timeout = run_timeout
        self._history = []
        self._history_replayable = True
        self._output = Queue()
        self._process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1,
        )
        self._finalizer = weakref.finalize(self, _cleanup_process, self._process)
        self._reader = threading.Thread(
            target=_read_output,
            args=(self._process.stdout, self._output),
            daemon=True,
        )
        self._reader.start()
        self._read_until_prompt(timeout=startup_timeout)

    def __enter__(self):
        """Return this runner for ``with`` statement usage."""
        return self

    def __exit__(self, exc_type, exc, traceback):
        """Close the Litex process when leaving a ``with`` block."""
        self.quit()
        return False

    def run(self, script, timeout=None):
        """Send script to litex and return its JSON results."""
        if not script.strip():
            raise ValueError("litex script is empty")

        results = self._run_script(script, timeout=timeout)
        self._record_run(script, results)
        return results

    def sandbox_run(self, script, timeout=None, commit=False):
        """Run script in a temporary Litex session, optionally committing on success."""
        if not self._history_replayable:
            raise RuntimeError(
                "sandbox_run is unavailable after a failed run; call clear() first"
            )

        sandbox = self.__class__(
            command=self.command,
            startup_timeout=self.startup_timeout,
            run_timeout=self.run_timeout,
        )
        try:
            for historical_script in self._history:
                sandbox.run(historical_script)
            sandbox_results = sandbox.run(script, timeout=timeout)
        finally:
            sandbox.quit()

        if not commit or not self._results_are_successful(sandbox_results):
            return sandbox_results

        return self.run(script, timeout=timeout)

    def clear(self):
        """Clear the litex terminal session."""
        return self.run("clear")

    def quit(self):
        """Stop the running litex process."""
        if not getattr(self, "_finalizer", None):
            return
        if self._finalizer.alive:
            self._finalizer()

    close = quit

    def _run_script(self, script, timeout=None):
        timeout = self.run_timeout if timeout is None else timeout
        self._ensure_running()

        if self._script_needs_file(script):
            return self._run_script_from_file(script, timeout=timeout)

        return self._run_repl_command(script.strip(), timeout=timeout)

    def _run_repl_command(self, command, timeout):
        self._ensure_running()
        if self._process.stdin is None:
            raise RuntimeError("litex process stdin is not available")

        self._process.stdin.write("{}\n".format(command))
        self._process.stdin.flush()
        output = self._read_until_prompt(timeout=timeout)
        return self._parse_json_results(output)

    def _run_script_from_file(self, script, timeout):
        tmp_file = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".lit",
            prefix="litexpy-",
            delete=False,
            encoding="utf-8",
        )
        try:
            tmp_file.write(script)
            if not script.endswith("\n"):
                tmp_file.write("\n")
            tmp_file.close()

            command = 'run_file "{}"'.format(tmp_file.name)
            results = self._run_repl_command(command, timeout=timeout)
            return self._unwrap_internal_run_file_results(results)
        finally:
            try:
                os.unlink(tmp_file.name)
            except OSError:
                pass

    def _read_until_prompt(self, timeout):
        deadline = time.monotonic() + timeout
        output = ""

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
                return output

    def _parse_json_results(self, output):
        decoder = JSONDecoder()
        results = []
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

        raise ValueError("litex output did not contain JSON objects: {!r}".format(output))

    def _record_run(self, script, results):
        stripped = script.strip()
        if stripped == "clear" and self._results_are_successful(results):
            self._history = []
            self._history_replayable = True
            return

        if self._results_are_successful(results) and self._history_replayable:
            self._history.append(script)
            return

        self._history_replayable = False

    def _results_are_successful(self, results):
        for result in self._walk_result_dicts(results):
            if result.get("result") != "success":
                return False
        return True

    def _walk_result_dicts(self, value):
        if isinstance(value, dict):
            yield value
            for nested in value.get("inside_results", []):
                for result in self._walk_result_dicts(nested):
                    yield result
            previous_error = value.get("previous_error")
            if previous_error is not None:
                for result in self._walk_result_dicts(previous_error):
                    yield result
            return

        if isinstance(value, list):
            for item in value:
                for result in self._walk_result_dicts(item):
                    yield result

    def _script_needs_file(self, script):
        stripped = script.strip()
        if "\n" in stripped or "\r" in stripped:
            return True
        if stripped.endswith(":"):
            return True
        if stripped != script:
            return True
        return False

    def _unwrap_internal_run_file_results(self, results):
        if (
            len(results) == 1
            and results[0].get("result") == "success"
            and results[0].get("type") == "RunFileStmt"
        ):
            return results[0].get("inside_results", [])
        return results

    def _ensure_running(self):
        if self._process.poll() is not None:
            raise RuntimeError("litex process is not running")


def _read_output(stdout, output):
    if stdout is None:
        output.put(None)
        return

    while True:
        chunk = stdout.read(1)
        if chunk == "":
            output.put(None)
            return
        output.put(chunk)


def _cleanup_process(process):
    if process.poll() is not None:
        _close_process_stdout(process)
        return

    if process.stdin is not None:
        try:
            process.stdin.close()
        except OSError:
            pass

    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    _close_process_stdout(process)


def _close_process_stdout(process):
    if process.stdout is None:
        return
    try:
        process.stdout.close()
    except OSError:
        pass


def _resolve_command(command):
    if command is not None:
        if isinstance(command, str):
            return [command]
        return list(command)

    env_command = os.environ.get("LITEXPY_LITEX_COMMAND")
    if env_command and env_command.strip():
        return shlex.split(env_command)

    env_bin = os.environ.get("LITEXPY_LITEX_BIN")
    if env_bin and env_bin.strip():
        return [env_bin]

    return ["litex"]
