import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import paper_workflow as workflow


class FakeCodex:
    """Replay local CLI output without starting a model or contacting Zotero."""

    def __init__(self, *outcomes):
        self.outcomes = iter(outcomes)
        self.calls = []
        self.processes = []

    def __call__(self, command, **kwargs):
        outcome = next(self.outcomes)
        self.calls.append(list(command))
        process = self.Process(command, kwargs, outcome)
        self.processes.append(process)
        return process

    class Process:
        def __init__(self, command, kwargs, outcome):
            self.command = command
            self.kwargs = kwargs
            self.outcome = outcome
            self.returncode = None
            self.terminated = False

        def communicate(self, prompt):
            self.prompt = prompt
            self.kwargs["stdout"].write(self.outcome.get("events", ""))
            self.kwargs["stderr"].write(self.outcome.get("stderr", ""))
            if "report" in self.outcome:
                output = Path(self.command[self.command.index("-o") + 1])
                output.write_text(json.dumps(self.outcome["report"]), encoding="utf8")
            if self.outcome.get("interrupt"):
                raise KeyboardInterrupt()
            self.returncode = self.outcome.get("exit_code", 0)
            return None, None

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        def wait(self):
            return self.returncode


class PaperWorkflowTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        for name, value in (("ROOT", self.root), ("WORKFLOWS", self.root / "local" / "workflows")):
            patcher = patch.object(workflow, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.evidence = self.root / "local" / "verification.md"
        self.evidence.parent.mkdir()
        self.evidence.write_text("This run's verification evidence.", encoding="utf8")

    def task(self, name="task"):
        path = workflow.WORKFLOWS / name / "task.json"
        workflow.save(path, {"request": "查找库内论文", "mode": "lookup", "status": "ready",
                             "attempts": [], "pending": []})
        return path

    def report(self):
        return {"answer": "已完成查库。", "checks": [
            {"item": item, "status": "通过", "evidence": "local/verification.md", "reason": ""}
            for item in sorted(workflow.REQUIRED["lookup"])
        ], "artifacts": ["local/verification.md"], "pending": [], "redlines": [],
            "zotero_record_writes": 0}

    def execute(self, path, cli):
        output = io.StringIO()
        with patch.object(workflow.shutil, "which", return_value="fake-codex"), \
                patch.object(workflow.subprocess, "Popen", side_effect=cli), redirect_stdout(output):
            code = workflow.execute(path)
        return code, json.loads(path.read_text("utf8")), output.getvalue()

    def test_incomplete_or_unsafe_reports_cannot_complete(self):
        cases = []
        for label, mutate, expected in (
            ("pending work", lambda r: r["pending"].append("补齐授权"), "pending"),
            ("failed check", lambda r: r["checks"][0].update(status="失败"), "needs_revision"),
            ("redline", lambda r: r["redlines"].append("超出范围写库"), "needs_revision"),
            ("missing evidence", lambda r: r["checks"][0].update(evidence="  "), "pending"),
            ("unverified check", lambda r: r["checks"][0].update(status="待验证"), "pending"),
            ("missing artifact", lambda r: r.update(artifacts=["local/missing.md"]), "pending"),
            ("missing required check", lambda r: r["checks"].pop(), "pending"),
            ("lookup wrote records", lambda r: r.update(zotero_record_writes=1), "needs_revision"),
        ):
            report = self.report()
            mutate(report)
            cases.append((label, report, expected))
        for index, (label, report, expected) in enumerate(cases):
            with self.subTest(label=label):
                code, task, output = self.execute(self.task(str(index)), FakeCodex({"report": report}))
                self.assertEqual(code, 1)
                self.assertEqual(task["status"], expected)
                self.assertEqual(json.loads(output)["status"], expected)

    def test_nonzero_exit_does_not_accept_report_or_reuse_previous_completion(self):
        path = self.task()
        code, previous, _ = self.execute(path, FakeCodex({"report": self.report()}))
        self.assertEqual(code, 0)
        answer = path.parent / "answer.md"
        previous_answer = answer.read_text("utf8")
        misleading_report = copy.deepcopy(self.report())
        misleading_report["answer"] = "This unsuccessful attempt must not replace the answer."
        code, task, output = self.execute(path, FakeCodex({"exit_code": 1, "report": misleading_report}))
        self.assertEqual(code, 1)
        self.assertEqual(task["status"], "interrupted")
        self.assertEqual(task["report"], previous["report"])
        self.assertEqual(answer.read_text("utf8"), previous_answer)
        self.assertEqual(task["attempts"][-1]["exit_code"], 1)
        self.assertTrue(task["pending"])
        self.assertEqual(json.loads(output)["status"], "interrupted")

    def test_resume_uses_saved_thread_id_and_public_output_hides_cli_details(self):
        path = self.task()
        session_id = "private-thread-7853"
        secret_error = "private stderr: local credential and attachment location"
        pending = self.report()
        pending["pending"] = ["补齐核验"]
        cli = FakeCodex(
            {"report": pending, "events": "not-json\n" + json.dumps(
                {"type": "thread.started", "thread_id": session_id}) + "\n", "stderr": secret_error},
            {"report": self.report()},
        )
        first_code, first_task, first_output = self.execute(path, cli)
        second_code, task, second_output = self.execute(path, cli)
        self.assertEqual((first_code, second_code), (1, 0))
        self.assertEqual(first_task["session_id"], session_id)
        self.assertEqual(task["status"], "completed")
        self.assertNotIn("resume", cli.calls[0])
        self.assertIn("resume", cli.calls[1])
        self.assertIn(session_id, cli.calls[1])
        self.assertNotIn("--last", cli.calls[1])
        for output in (first_output, second_output):
            public = json.loads(output)
            self.assertNotIn("session_id", public)
            self.assertNotIn(session_id, output)
            self.assertNotIn(secret_error, output)
        self.assertEqual((path.parent / "attempt-001" / "stderr.log").read_text("utf8"), secret_error)

    def test_interrupt_preserves_task_and_discovered_thread_for_recovery(self):
        path = self.task()
        cli = FakeCodex({"interrupt": True, "events": json.dumps(
            {"type": "thread.started", "thread_id": "recoverable-thread"}) + "\n"})
        code, task, output = self.execute(path, cli)
        self.assertEqual(code, 1)
        self.assertTrue(cli.processes[0].terminated)
        self.assertEqual(task["status"], "interrupted")
        self.assertEqual(task["session_id"], "recoverable-thread")
        self.assertEqual(len(task["attempts"]), 1)
        self.assertEqual(task["attempts"][0]["status"], "interrupted")
        self.assertTrue(task["attempts"][0]["finished_at"])
        self.assertTrue(task["pending"])
        self.assertEqual(json.loads(output)["status"], "interrupted")
        self.assertFalse((path.parent / "answer.md").exists())

    def test_checkpoint_is_persisted_and_available_to_status(self):
        path = self.task()
        relative = path.relative_to(self.root).as_posix()
        for stage in ("lookup", "verify"):
            with patch.object(sys, "argv", ["paper_workflow.py", "checkpoint", relative,
                                             "--stage", stage]), redirect_stdout(io.StringIO()):
                self.assertEqual(workflow.main(), 0)
        progress = json.loads((path.parent / "progress.json").read_text("utf8"))
        self.assertEqual([c["stage"] for c in progress["checkpoints"]], ["lookup", "verify"])
        output = io.StringIO()
        with patch.object(sys, "argv", ["paper_workflow.py", "status", relative]), redirect_stdout(output):
            self.assertEqual(workflow.main(), 0)
        status = json.loads(output.getvalue())
        self.assertEqual(status["stage"], "verify")
        self.assertEqual(status["status"], "ready")

    def test_desktop_finish_and_resume_preserve_history_without_subprocess(self):
        path = self.task()
        output = io.StringIO()
        with patch.object(workflow.subprocess, "Popen") as launch, redirect_stdout(output):
            self.assertEqual(workflow.prepare_desktop(path), 0)
            first = path.parent / "attempt-001" / "result.json"
            pending = self.report()
            pending["pending"] = ["private user detail"]
            workflow.save(first, pending)
            self.assertEqual(workflow.finish_desktop(path), 1)
            snapshot = first.read_bytes()
            self.assertEqual(workflow.prepare_desktop(path, "条件已满足，继续"), 0)
            second = path.parent / "attempt-002" / "result.json"
            self.assertFalse(second.exists())
            workflow.save(second, self.report())
            self.assertEqual(workflow.finish_desktop(path), 0)
            launch.assert_not_called()
        task = json.loads(path.read_text("utf8"))
        self.assertEqual(task["status"], "completed")
        self.assertEqual([a["status"] for a in task["attempts"]], ["pending", "completed"])
        self.assertEqual(first.read_bytes(), snapshot)
        self.assertEqual(task["report"], second.relative_to(self.root).as_posix())
        self.assertIn("条件已满足，继续", (second.parent / "prompt.txt").read_text("utf8"))
        self.assertNotIn("private user detail", output.getvalue())
        self.assertEqual((path.parent / "answer.md").read_text("utf8"), self.report()["answer"])

    def test_desktop_invalid_result_cannot_replace_a_valid_answer(self):
        for name, invalid in (("missing", None), ("bad-types", {"checks": "invalid"})):
            with self.subTest(case=name), redirect_stdout(io.StringIO()):
                path = self.task(name)
                self.assertEqual(workflow.prepare_desktop(path), 0)
                old_answer = path.parent / "answer.md"
                old_answer.write_text("Earlier answer", encoding="utf8")
                if invalid is not None:
                    workflow.save(path.parent / "attempt-001" / "result.json", invalid)
                self.assertEqual(workflow.finish_desktop(path), 1)
                task = json.loads(path.read_text("utf8"))
                self.assertEqual(task["status"], "interrupted")
                self.assertEqual(task["attempts"][-1]["status"], "interrupted")
                self.assertEqual(old_answer.read_text("utf8"), "Earlier answer")

    def test_abrupt_stop_recovers_cli_session_and_resets_current_stage(self):
        path = self.task()
        old = path.parent / "attempt-001"
        old.mkdir()
        session_id = "saved-only-in-events"
        (old / "events.jsonl").write_text(json.dumps(
            {"type": "thread.started", "thread_id": session_id}) + "\n", encoding="utf8")
        task = json.loads(path.read_text("utf8"))
        task.update(status="running", attempts=[{
            "started_at": "earlier", "status": "running", "executor": "cli",
            "folder": old.relative_to(self.root).as_posix(),
        }])
        workflow.save(path, task)
        workflow.save(path.parent / "progress.json", {"checkpoints": [
            {"time": "earlier", "stage": "verify", "attempt": 1},
        ]})
        cli = FakeCodex({"report": self.report()})
        code, task, output = self.execute(path, cli)
        self.assertEqual(code, 0)
        self.assertIn(session_id, cli.calls[0])
        self.assertIn("resume", cli.calls[0])
        self.assertEqual(task["attempts"][0]["status"], "interrupted")
        self.assertTrue(task["attempts"][0]["finished_at"])
        self.assertNotIn("stage", json.loads(output))


if __name__ == "__main__":
    unittest.main()
