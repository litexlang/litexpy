import shutil
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import litexpy  # noqa: E402


def all_success(results):
    return all(result.get("result") == "success" for result in results)


@unittest.skipUnless(shutil.which("litex"), "litex command is not installed")
class RunnerIntegrationTests(unittest.TestCase):
    def test_runs_single_line_multiline_and_block_scripts(self):
        block_script = "\n".join(
            [
                "forall x R:",
                "    x = 2",
                "    =>:",
                "        x + 1 = 3",
                "        x^2 = 4",
            ]
        )

        with litexpy.Runner(command=["litex"], run_timeout=10) as runner:
            single = runner.run("1 = 1")
            multiline = runner.run("1 = 1\n0 = 0")
            block = runner.run(block_script)

        self.assertTrue(all_success(single))
        self.assertEqual([result["stmt"] for result in multiline], ["1 = 1", "0 = 0"])
        self.assertTrue(all_success(multiline))
        self.assertEqual(len(block), 1)
        self.assertEqual(block[0]["type"], "ForallFact")
        self.assertEqual(block[0]["result"], "success")

    def test_session_state_and_clear(self):
        with litexpy.Runner(command=["litex"], run_timeout=10) as runner:
            runner.run("have a R = 1")
            known = runner.run("a = 1")
            runner.clear()
            after_clear = runner.run("a = 1")

        self.assertEqual(known[0]["result"], "success")
        self.assertEqual(after_clear[0]["result"], "error")

    def test_sandbox_uses_context_without_polluting_main_session(self):
        with litexpy.Runner(command=["litex"], run_timeout=10) as runner:
            runner.run("have base R = 1")
            sandbox = runner.sandbox_run("have trial R = 2\nbase = 1")
            base_still_known = runner.run("base = 1")
            trial_not_known = runner.run("trial = 2")

        self.assertTrue(all_success(sandbox))
        self.assertEqual(base_still_known[0]["result"], "success")
        self.assertEqual(trial_not_known[0]["result"], "error")

    def test_sandbox_commit_success_adds_facts_to_main_session(self):
        with litexpy.Runner(command=["litex"], run_timeout=10) as runner:
            runner.run("have base R = 1")
            sandbox = runner.sandbox_run("have committed R = 2\nbase = 1", commit=True)
            committed_known = runner.run("committed = 2")

        self.assertTrue(all_success(sandbox))
        self.assertEqual(committed_known[0]["result"], "success")

    def test_sandbox_commit_failure_leaves_main_session_unchanged(self):
        with litexpy.Runner(command=["litex"], run_timeout=10) as runner:
            runner.run("have base R = 1")
            sandbox = runner.sandbox_run(
                "have rejected R = 3\nunknown_identifier = 2",
                commit=True,
            )
            base_still_known = runner.run("base = 1")
            rejected_not_known = runner.run("rejected = 3")

        self.assertFalse(all_success(sandbox))
        self.assertEqual(base_still_known[0]["result"], "success")
        self.assertEqual(rejected_not_known[0]["result"], "error")

    def test_failed_statement_does_not_kill_runner(self):
        with litexpy.Runner(command=["litex"], run_timeout=10) as runner:
            failed = runner.run("unknown_identifier = 2")
            later = runner.run("1 = 1")

        self.assertEqual(failed[0]["result"], "error")
        self.assertEqual(later[0]["result"], "success")


if __name__ == "__main__":
    unittest.main()
