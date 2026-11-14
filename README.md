# embodied-paper-reader

一个面向具身智能研究的论文阅读工作流。目标是让读者能讲清论文贡献、回到原文核查实验结论、了解复现条件，并在用户提出时判断自己的设备适合做哪一步。

项目 Skill 位于 [.agents/skills/embodied-paper-reader/](.agents/skills/embodied-paper-reader/SKILL.md)，配套[验收表](docs/acceptance.md)与本机 Zotero 脚本。OpenVLA 已用于验证正式版与 arXiv v3 的入库及重试。

## 两种请求

- **指定论文**。例如“帮我读 OpenVLA”。根据标题、作者、团队、日期或论文标识辨认目标。优先读你指定的版本；未指定时先复用库中已核实的全文。另行获取时优先正式出版版，其次采用最新可核实的 arXiv 修订。交付中文导读，并在本机 Zotero 的同一父条目下保存该版 PDF 和导读子笔记。
- **按主题找论文**。例如“从早到近梳理 VLA 的重要论文”。默认目标 6 篇，用户指定数量优先。记录实际检索来源、查询式、时间窗、截止日和筛选依据，在一张时间表里标出奠基工作、关键转折、期末代表及其证据。篇数不足或阶段缺失时，说明检索和排除过哪些工作、还有哪些缺口。用户选篇前，本次请求向 Zotero 新增 0 条记录。[固定时间窗的路线验收样例](docs/acceptance.md#route-example)

## 单篇交付

先用一段话交代背景、研究问题、方法和效果。再解释模型的输入与输出、关键设计、支撑结论的实验和适用边界。在导读及 Zotero 笔记中，关键数字就近标出原文章节、图表或官方代码位置。末尾默认推荐 3 篇相关论文，每篇说明技术关系和一个值得带着读的问题。引用上下文与关联论文的官方摘要能支持这层关系时即可推荐。

中文导读用简短加粗突出研究问题、核心方法、主要结果、局限和复现门槛，方便快速扫读，每段优先突出 1–2 处。结果数字附近保留比较对象、任务范围和单位。对话使用 Markdown 加粗，Zotero 的 HTML 笔记使用 `<strong>`，让重点在两处都可见。

复现条件分推理、微调、仿真、真机四项。普通精读只整理官方条件。若你问“我的设备能跑吗”，优先用你在本轮给出的参数，其次用已有的 `local/device.md`。仅在目标确为当前电脑时，才对缺失参数做只读探测。缺少设备信息时，单列待验证的个人判断。

只有摘要时，只转述作者报告的事实和数字，不自行计算差值或排名。若原请求包含全文精读和入库，缺失的正文、PDF 或笔记列为待验证。具体判定见[核验表](docs/acceptance.md)。

## Zotero 中如何复读与复核

已有父条目和经核实的同版 PDF 可复用。导读标题带论文简称和版本，笔记头部标明取证日期、已核验内容及待补原因。同版摘要补成全文时更新原笔记，保留其 Key 和用户批注。已有笔记无法安全更新时报告待补。

首版脚本在一次执行中完成写前盘点、写入或更新、回读验证和写后盘点。重试从已落盘的记录和 Zotero 实际状态恢复。首版审计文件保存在 `local/zotero-audit/`，采用可跨平台使用的文件名。对话只展示脱敏结果、计数变化、核验时间和详单相对路径。

### 运行同步脚本

使用 Python 3.10+，打开 Zotero Desktop 10 并启用本机 API。在仓库根目录运行以下命令。第二次运行同步命令即可核验重试增量。

```powershell
python -m pip install -r requirements.txt
python -X utf8 scripts/zotero_sync.py local/openvla/paper.json
```

输入是一份已核对版本的论文清单，与 PDF 和 HTML 中文导读放在同一目录，字段见 [Skill 同步输入约定](.agents/skills/embodied-paper-reader/references/sync-input.md)。当前电脑的 v3 样品为 `local/openvla/paper.json`，正式版为 `local/openvla/publisher.json`。新检出的项目按 Skill 准备材料。

同步前可只读检查库内已有论文和版本，确认后导出已核实的 PDF 副本。

```powershell
python -X utf8 scripts/zotero_lookup.py "OpenVLA"
python -X utf8 scripts/zotero_lookup.py "OpenVLA" --export-version "arxiv:2406.09246v3"
```

脚本操作 Zotero Desktop 10 个人库。首次写入由 Zotero 弹窗授权，密钥默认保留在本次运行内存中；也可通过 `ZOTERO_LOCAL_API_KEY` 提供已取得的本地密钥。同步退出码 0 表示本机回读通过，内容事实按核验表另行验收。

## 使用项目 Skill

在本仓库目录打开 Codex 新对话，输入“帮我读 OpenVLA”。也可显式输入“用 $embodied-paper-reader 帮我读 OpenVLA”。Skill 根据请求查找论文、核对版本、读取全文、生成带重点加粗的中文导读，再调用脚本同步到 Zotero。只请求摘要或选文时按对应范围交付。

Skill 随仓库使用，引用根目录脚本与核验表。使用 Git 克隆完整仓库后，从仓库目录启动对话。

已在本机独立对话中验证自动触发、OpenVLA 已有版本复用、Octo 首次获取与入库、固定时间窗的六篇主题路线，以及选定 RT-2 v1 后的精读与入库。三篇单篇测试均取得重复执行零新增的记录。原文统计口径和未公开复现材料的缺项按核验表保留待验证。这些记录覆盖当前本机环境，其他 Zotero 版本与部署环境仍需实测。

## 开发顺序

1. 用 OpenVLA 完成单篇样品，按核验表验证全文导读、Zotero 入库和重复执行。
2. 按样品反馈将规则与脚本封装成项目级 Codex Skill。
3. 加入按技术演进选文的主题阅读路线。
4. 在新对话中，用另一篇论文和一次中断重试验收可复用性。

Git 跟踪工作流规则、脚本和测试用例。论文 PDF、个人导读和 Zotero 数据保存在本机。需要暂存的阅读材料可放在仓库中由 Git 忽略的 `local/` 目录。
