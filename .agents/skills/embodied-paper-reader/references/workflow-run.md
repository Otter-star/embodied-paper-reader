# 持久任务入口

工作目录为已解析的仓库根目录。按用户请求明确选择 lookup（只读找回）、read（精读并入库）或 route（选文路线，选篇前零写入）。默认在当前 Codex 对话执行，复用本对话的工具与审批机制。

```powershell
python -X utf8 scripts/paper_workflow.py run "<用户原始请求>" --mode lookup --executor desktop
```

命令只创建进行中的任务与执行说明，没有调用另一个模型。读取输出的 prompt.txt、schema.json，并按需解析 task.json 中的请求、范围、状态和尝试目录，然后按 Skill 实际检索、查库或阅读。task.json 可能含 CLI 内部会话 ID，原始任务与审计不要整份打印，内部字段由本机脚本处理。不能将 running 状态或提示文件路径当作完成交付，也不要等待用户再次发“继续”。

在实际阶段开始前记录进度。阶段记录只说明执行到这里，不能证明内容已通过。

```powershell
python -X utf8 scripts/paper_workflow.py checkpoint local/workflows/<任务>/task.json --stage lookup
```

产物、具体证据和待补原因写入本次 attempt 目录的 result.json，结构遵从该目录的 schema.json。检查 item 对应关系如下。

| 模式 | 必需检查 item |
| --- | --- |
| lookup | identity、library_read、privacy、zero_writes |
| read | identity、explanation、experiments、reproduction、related、zotero、privacy |
| route | identity、route、privacy、zero_writes |

每个检查写通过／失败／待验证／不适用、具体证据位置和必要原因。子断言可在 item 下细分，主项状态如实汇总；当前模式的必需主项不能整体标不适用。库内无匹配也可通过只读查询核验，identity 此时记录查找目标和实际查询范围，答复明确“本次未查到”，不能声称论文已在库中。证据不足与超出请求范围分别处理。

answer 保存脱敏中文交付。artifacts 使用 local 下实际非空文件的相对路径，至少包含本次核验记录或审计详单。pending 列缺口与恢复条件，redlines 记录实际违例，zotero_record_writes 只计本次库记录写操作。内部 Key、存储路径及摘录仅保留本机详单。科学结论、图片可读与入库事实仍按核验表核对，不能靠“结果结构合法”判通过。

```powershell
python -X utf8 scripts/paper_workflow.py finish local/workflows/<任务>/task.json
```

finish 汇总后向用户交付答复、实际状态和任务相对路径。有缺项时报告待补，保留成果；环境允许恢复则继续补缺。换对话或模型时，用同一任务路径恢复，先读取原始请求、原版本约束、先前尝试、待补与现有产物。

```powershell
python -X utf8 scripts/paper_workflow.py resume local/workflows/<任务>/task.json --executor desktop --message "<用户补充>"
```

恢复创建新的 attempt，旧记录保留。前一轮成功不能替代本轮要求重新核实的事实。用户改变了论文、版本或请求范围时，明确保存该变化；当前入口不改变已有任务 mode，范围改变时创建新任务并引用前任务的核验记录。

独立 CLI 后台执行需明确使用 `--executor cli`；它使用本机 Codex CLI 和原权限设置，不适合从命令执行工具不能启动的环境中反复嵌套重试。桌面与 CLI 版本的部署状态见仓库 `docs/workflow.md`。
