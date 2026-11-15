"""Record and resume paper-reader tasks in Codex Desktop or the local CLI."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess

from filelock import FileLock, Timeout

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / "local" / "workflows"
REQUIRED = {
    "lookup": {"identity", "library_read", "privacy", "zero_writes"},
    "route": {"identity", "route", "privacy", "zero_writes"},
    "read": {"identity", "explanation", "experiments", "reproduction", "related", "zotero", "privacy"},
}
STATUSES = ["通过", "失败", "待验证", "不适用"]
SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["answer", "checks", "artifacts", "pending", "redlines", "zotero_record_writes"],
    "properties": {
        "answer": {"type": "string"},
        "checks": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["item", "status", "evidence", "reason"],
            "properties": {"item": {"type": "string"}, "status": {"type": "string", "enum": STATUSES},
                           "evidence": {"type": "string"}, "reason": {"type": "string"}},
        }},
        "artifacts": {"type": "array", "items": {"type": "string"}},
        "pending": {"type": "array", "items": {"type": "string"}},
        "redlines": {"type": "array", "items": {"type": "string"}},
        "zotero_record_writes": {"type": "integer", "minimum": 0},
    },
}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf8")
    temporary.replace(path)


def load_task(value):
    path = (ROOT / value).resolve()
    if not path.is_relative_to(WORKFLOWS.resolve()) or path.name != "task.json":
        raise ValueError("任务文件应位于 local/workflows/<任务>/task.json")
    return path, json.loads(path.read_text("utf8"))


def assess(report, mode):
    if not isinstance(report, dict) or set(report) != set(SCHEMA["required"]):
        raise ValueError("结果字段与约定不符")
    if not isinstance(report["answer"], str) or type(report["zotero_record_writes"]) is not int or report["zotero_record_writes"] < 0:
        raise ValueError("结果字段类型不符")
    for field in ("artifacts", "pending", "redlines"):
        if not isinstance(report[field], list) or not all(isinstance(v, str) for v in report[field]):
            raise ValueError("结果列表字段类型不符")
    if not isinstance(report["checks"], list):
        raise ValueError("核验项需为列表")
    for check in report["checks"]:
        if not isinstance(check, dict) or set(check) != {"item", "status", "evidence", "reason"} or not all(isinstance(v, str) for v in check.values()):
            raise ValueError("核验项字段类型不符")
    checks = report["checks"]
    if report["redlines"] or any(c["status"] == "失败" for c in checks):
        return "needs_revision"
    if mode in {"lookup", "route"} and report["zotero_record_writes"] != 0:
        return "needs_revision"
    by_item = {c["item"]: c for c in checks}
    if not REQUIRED[mode].issubset(by_item) or not report["artifacts"]:
        return "pending"
    for item in REQUIRED[mode]:
        if by_item[item]["status"] == "不适用":
            return "pending"
    for check in checks:
        if check["status"] not in STATUSES:
            raise ValueError("未知核验状态")
        if check["status"] == "待验证" or (check["status"] == "通过" and not check["evidence"].strip()):
            return "pending"
        if check["status"] == "不适用" and not check["reason"].strip():
            return "pending"
    for artifact in report["artifacts"]:
        path = (ROOT / artifact).resolve()
        if Path(artifact).is_absolute() or not path.is_relative_to(ROOT / "local") or not path.is_file() or path.stat().st_size == 0:
            return "pending"
    return "pending" if report["pending"] else "completed"


def prompt_for(task, task_path, message):
    relative = task_path.relative_to(ROOT).as_posix()
    return f"""使用本仓库 .agents/skills/embodied-paper-reader/SKILL.md 完成以下任务。
原始请求：{task['request']}
范围：{task['mode']}。lookup仅查库，route选篇前零写库，read按Skill精读入库。
本次补充：{message}
任务记录：{relative}。续跑先读该任务、此前尝试与已有产物，只补缺项，保持原版本约束。
任务记录按需在本机解析，仅返回请求、范围、状态和尝试目录；CLI会话ID由脚本读取，不能整份打印原始任务、审计或日志。
开始每个实际阶段前，用本机命令记录阶段：
python -X utf8 scripts/paper_workflow.py checkpoint {relative} --stage <阶段名>
阶段可按任务采用 identity、lookup、search、read、guide、sync、verify；无需执行不适用阶段。
不得修改项目代码、规则或测试。读取材料与全部产物保存在local；内部Key/路径/原始输出留本机。
最终answer是脱敏中文答复，关键部分加粗；图用绝对路径内嵌。checks按核验表填写，
必须包含这些item：{', '.join(sorted(REQUIRED[task['mode']]))}。
通过项给具体证据位置，非适用项说明范围理由；缺证据写待验证，并列pending恢复条件。
artifacts给本轮实际产物的仓库相对路径，至少包括本轮核验记录/查库详单。
redlines列实际触犯的红线，没有则空数组。zotero_record_writes为本次库记录写次数。
网络、授权或材料不足时交付已有成果和待补，不自动无限重试；不绕过沙箱、审批或用户修改保护。
进程完成和格式正确不代表内容验收通过。不要虚构证据，不要以历史样例替代本轮检查。
"""


def command_for(executable, folder, session_id=None):
    command = [executable, "exec", "-C", str(ROOT), "--sandbox", "workspace-write"]
    if session_id:
        command.extend(["resume"])
    command.extend(["--json", "--output-schema", str(folder / "schema.json"),
                    "-o", str(folder / "result.json")])
    if session_id:
        command.append(session_id)
    return command + ["-"]


def recover_session(task):
    sessions = {task["session_id"]} if task.get("session_id") else set()
    for attempt in task["attempts"]:
        path = ROOT / attempt["folder"] / "events.jsonl"
        if not path.exists():
            continue
        for line in path.read_text("utf8").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("type") == "thread.started" and isinstance(event.get("thread_id"), str) and event["thread_id"]:
                sessions.add(event["thread_id"])
    if len(sessions) > 1:
        raise ValueError("任务记录存在不同会话，需先核对本地日志")
    return next(iter(sessions), None)


def prepare_attempt(task_path, task, executor, message):
    if task["status"] == "running" and task["attempts"]:
        task["attempts"][-1].update(status="interrupted", finished_at=now())
    folder = task_path.parent / f"attempt-{len(task['attempts']) + 1:03d}"
    folder.mkdir()
    task["attempts"].append({"started_at": now(), "executor": executor,
                             "folder": folder.relative_to(ROOT).as_posix(), "status": "running"})
    task["status"] = "running"
    task["pending"] = []
    save(task_path, task)
    save(folder / "schema.json", SCHEMA)
    prompt = prompt_for(task, task_path, message)
    if executor == "desktop":
        prompt += "\n在当前 Codex 对话执行本任务，不再启动子 Codex。完成后将结构化结果写入本次目录 result.json，运行 paper_workflow.py finish <任务路径> 完成核验。\n"
    (folder / "prompt.txt").write_text(prompt, encoding="utf8")
    return folder, prompt


def accept_report(task_path, task, folder):
    report = json.loads((folder / "result.json").read_text("utf8"))
    task["status"] = assess(report, task["mode"])
    task["pending"] = report["pending"]
    task["report"] = (folder / "result.json").relative_to(ROOT).as_posix()
    (task_path.parent / "answer.md").write_text(report["answer"], encoding="utf8")


def prepare_desktop(task_path, message=""):
    with FileLock(str(task_path.parent / "run.lock"), timeout=0):
        task = json.loads(task_path.read_text("utf8"))
        prepare_attempt(task_path, task, "desktop", message)
        show(task_path, task)
        return 0


def finish_desktop(task_path):
    with FileLock(str(task_path.parent / "run.lock"), timeout=0):
        task = json.loads(task_path.read_text("utf8"))
        if not task["attempts"] or task["attempts"][-1].get("executor") != "desktop" or task["status"] != "running":
            raise ValueError("没有进行中的桌面执行，请先启动或恢复任务")
        attempt = task["attempts"][-1]
        folder = ROOT / attempt["folder"]
        try:
            accept_report(task_path, task, folder)
        except (OSError, ValueError, KeyError) as error:
            task["status"] = "interrupted"
            task["pending"] = ["修正本次结果文件后恢复任务"]
            (folder / "error.txt").write_text(str(error), encoding="utf8")
        attempt.update(status=task["status"], finished_at=now())
        save(task_path, task)
        show(task_path, task)
        return 0 if task["status"] == "completed" else 1


def execute(task_path, message=""):
    with FileLock(str(task_path.parent / "run.lock"), timeout=0):
        task = json.loads(task_path.read_text("utf8"))
        task["session_id"] = recover_session(task)
        folder, prompt = prepare_attempt(task_path, task, "cli", message)
        attempt = task["attempts"][-1]
        process = None
        try:
            executable = shutil.which("codex")
            if not executable:
                raise RuntimeError("未找到本机 Codex CLI")
            with (folder / "events.jsonl").open("w", encoding="utf8") as events, \
                    (folder / "stderr.log").open("w", encoding="utf8") as errors:
                process = subprocess.Popen(command_for(executable, folder, task.get("session_id")),
                                           cwd=ROOT, stdin=subprocess.PIPE, stdout=events, stderr=errors,
                                           text=True, encoding="utf8")
                process.communicate(prompt)
            attempt["exit_code"] = process.returncode
            if process.returncode != 0:
                raise RuntimeError("Codex 执行未完成，详见本地运行日志")
            accept_report(task_path, task, folder)
        except (KeyboardInterrupt, OSError, ValueError, KeyError, RuntimeError) as error:
            if process and process.poll() is None:
                process.terminate()
                process.wait()
            task["status"] = "interrupted"
            task["pending"] = ["查看本地日志并恢复该任务"]
            (folder / "error.txt").write_text(str(error), encoding="utf8")
        finally:
            try:
                task["session_id"] = recover_session(task)
            except ValueError as error:
                task["status"] = "interrupted"
                task["pending"] = ["核对本地会话记录后续跑"]
                (folder / "error.txt").write_text(str(error), encoding="utf8")
            attempt.update(finished_at=now(), status=task["status"])
            save(task_path, task)
        show(task_path, task)
        return 0 if task["status"] == "completed" else 1


def show(path, task):
    result = {"task": path.relative_to(ROOT).as_posix(), "status": task["status"],
              "attempts": len(task["attempts"]), "pending_count": len(task.get("pending", []))}
    if task["attempts"]:
        attempt = task["attempts"][-1]
        result["executor"] = attempt.get("executor", "cli")
        if result["executor"] == "desktop":
            result["prompt"] = attempt["folder"] + "/prompt.txt"
    progress = path.parent / "progress.json"
    if progress.exists():
        current = [c for c in json.loads(progress.read_text("utf8"))["checkpoints"]
                   if c["attempt"] == len(task["attempts"])]
        if current:
            result["stage"] = current[-1]["stage"]
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    run = actions.add_parser("run")
    run.add_argument("request")
    run.add_argument("--mode", choices=REQUIRED, default="read")
    run.add_argument("--executor", choices=["desktop", "cli"], default="desktop")
    run.add_argument("--prepare-only", action="store_true")
    for action in ("resume", "status", "checkpoint", "finish"):
        command = actions.add_parser(action)
        command.add_argument("task")
        if action == "resume":
            command.add_argument("--message", default="继续原任务，仅补缺项")
            command.add_argument("--executor", choices=["desktop", "cli"], default="desktop")
        if action == "checkpoint":
            command.add_argument("--stage", required=True,
                                 choices=["identity", "lookup", "search", "read", "guide", "sync", "verify"])
    args = parser.parse_args()
    if args.action == "run":
        identifier = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        path = WORKFLOWS / identifier / "task.json"
        task = {"request": args.request, "mode": args.mode, "created_at": now(),
                "status": "ready", "attempts": [], "pending": []}
        save(path, task)
        if args.prepare_only:
            show(path, task)
            return 0
        return prepare_desktop(path) if args.executor == "desktop" else execute(path)
    path, task = load_task(args.task)
    if args.action == "resume":
        return prepare_desktop(path, args.message) if args.executor == "desktop" else execute(path, args.message)
    if args.action == "finish":
        return finish_desktop(path)
    if args.action == "checkpoint":
        progress = path.parent / "progress.json"
        data = json.loads(progress.read_text("utf8")) if progress.exists() else {"checkpoints": []}
        data["checkpoints"].append({"time": now(), "stage": args.stage, "attempt": len(task["attempts"])})
        save(progress, data)
    show(path, task)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, Timeout):
        raise SystemExit("任务未启动：检查任务路径、读写权限或是否已有运行中的任务")
