import json
import sys
import unittest
from pathlib import Path
from queue import Queue
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import litexpy  # noqa: E402


class FakeStdout:
    def __init__(self):
        self._queue = Queue()

    def feed(self, text):
        for char in text:
            self._queue.put(char)

    def close(self):
        self._queue.put("")

    def read(self, size):
        return self._queue.get(timeout=1)


class FakeStdin:
    def __init__(self, process):
        self.process = process
        self.closed = False

    def write(self, text):
        self.process.writes.append(text)
        command = text.strip()
        self.process.handle_command(command)

    def flush(self):
        pass

    def close(self):
        self.closed = True
        self.process.stdin_closed = True


class FakePopen:
    instances = []

    def __init__(self, command, **kwargs):
        self.command = command
        self.kwargs = kwargs
        self.stdout = FakeStdout()
        self.stdin = FakeStdin(self)
        self.returncode = None
        self.stdin_closed = False
        self.writes = []
        self.file_contents = []
        FakePopen.instances.append(self)
        self.stdout.feed("Litex version test\n>>> ")

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = 0
        self.stdout.close()
        return self.returncode

    def terminate(self):
        self.returncode = -15
        self.stdout.close()

    def kill(self):
        self.returncode = -9
        self.stdout.close()

    def handle_command(self, command):
        if command == "bad":
            self._feed_result({"result": "error", "stmt": "bad"})
            return

        if command == "sandbox bad":
            self._feed_result(
                {
                    "result": "error",
                    "stmt": "sandbox bad",
                    "previous_error": {"result": "error", "stmt": "inner bad"},
                }
            )
            return

        if command.startswith('run_file "'):
            file_path = command[len('run_file "') : -1]
            self.file_contents.append(Path(file_path).read_text(encoding="utf-8"))
            if "sandbox bad" in self.file_contents[-1]:
                result = {
                    "result": "success",
                    "type": "RunFileStmt",
                    "inside_results": [
                        {"result": "success", "stmt": "have c R = 3"},
                        {"result": "error", "stmt": "sandbox bad"},
                    ],
                }
            else:
                result = {
                    "result": "success",
                    "type": "RunFileStmt",
                    "inside_results": [
                        {"result": "success", "stmt": "1 = 1"},
                        {"result": "success", "stmt": "0 = 0"},
                    ],
                }
            self._feed_result(result)
            return

        self._feed_result({"result": "success", "stmt": command})

    def _feed_result(self, result):
        self.stdout.feed(json.dumps(result) + "\n>>> ")


class RunnerUnitTests(unittest.TestCase):
    def setUp(self):
        FakePopen.instances = []

    def test_command_is_used_and_context_manager_closes_process(self):
        with patch("litexpy._runner.subprocess.Popen", FakePopen):
            with litexpy.Runner(command=["fake-litex", "--detail"]) as runner:
                results = runner.run("1 = 1")

            process = FakePopen.instances[0]
            self.assertEqual(process.command, ["fake-litex", "--detail"])
            self.assertTrue(process.stdin_closed)
            self.assertEqual(results[0]["stmt"], "1 = 1")

    def test_multiline_script_uses_temp_file_and_flattens_run_file_results(self):
        with patch("litexpy._runner.subprocess.Popen", FakePopen):
            runner = litexpy.Runner(command=["fake-litex"])
            try:
                results = runner.run("1 = 1\n0 = 0")
            finally:
                runner.quit()

        process = FakePopen.instances[0]
        self.assertEqual([result["stmt"] for result in results], ["1 = 1", "0 = 0"])
        self.assertTrue(process.writes[-1].startswith('run_file "'))
        self.assertEqual(process.file_contents[-1], "1 = 1\n0 = 0\n")

    def test_sandbox_replays_history_in_separate_process(self):
        with patch("litexpy._runner.subprocess.Popen", FakePopen):
            runner = litexpy.Runner(command=["fake-litex"])
            try:
                runner.run("have a R = 1")
                results = runner.sandbox_run("a = 1")
            finally:
                runner.quit()

        main_process = FakePopen.instances[0]
        sandbox_process = FakePopen.instances[1]
        self.assertEqual(results[0]["stmt"], "a = 1")
        self.assertEqual(main_process.writes, ["have a R = 1\n"])
        self.assertEqual(sandbox_process.writes, ["have a R = 1\n", "a = 1\n"])

    def test_sandbox_commit_preflights_then_runs_in_main_process(self):
        with patch("litexpy._runner.subprocess.Popen", FakePopen):
            runner = litexpy.Runner(command=["fake-litex"])
            try:
                runner.run("have a R = 1")
                results = runner.sandbox_run("a = 1", commit=True)
            finally:
                runner.quit()

        main_process = FakePopen.instances[0]
        sandbox_process = FakePopen.instances[1]
        self.assertEqual(results[0]["stmt"], "a = 1")
        self.assertEqual(main_process.writes, ["have a R = 1\n", "a = 1\n"])
        self.assertEqual(sandbox_process.writes, ["have a R = 1\n", "a = 1\n"])

    def test_sandbox_commit_does_not_run_failed_preflight_in_main_process(self):
        with patch("litexpy._runner.subprocess.Popen", FakePopen):
            runner = litexpy.Runner(command=["fake-litex"])
            try:
                runner.run("have a R = 1")
                results = runner.sandbox_run("sandbox bad", commit=True)
            finally:
                runner.quit()

        main_process = FakePopen.instances[0]
        sandbox_process = FakePopen.instances[1]
        self.assertEqual(results[0]["result"], "error")
        self.assertEqual(main_process.writes, ["have a R = 1\n"])
        self.assertEqual(sandbox_process.writes, ["have a R = 1\n", "sandbox bad\n"])

    def test_failed_run_blocks_sandbox_until_clear(self):
        with patch("litexpy._runner.subprocess.Popen", FakePopen):
            runner = litexpy.Runner(command=["fake-litex"])
            try:
                runner.run("bad")
                with self.assertRaisesRegex(RuntimeError, "call clear"):
                    runner.sandbox_run("1 = 1")

                runner.clear()
                results = runner.sandbox_run("1 = 1")
            finally:
                runner.quit()

        self.assertEqual(results[0]["result"], "success")

    def test_json_parser_ignores_banner_and_multiple_objects(self):
        runner = object.__new__(litexpy.Runner)
        results = runner._parse_json_results(
            'banner\n{"result":"success","stmt":"1 = 1"}\n'
            'noise\n{"result":"error","stmt":"1 = 0"}\n>>> '
        )

        self.assertEqual([result["stmt"] for result in results], ["1 = 1", "1 = 0"])


if __name__ == "__main__":
    unittest.main()
