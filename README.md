# embodied-paper-reader

一个面向具身智能研究的论文阅读工作流。目标是让读者能讲清论文贡献、回到原文核查实验结论、了解复现条件，并在用户提出时判断自己的设备适合做哪一步。

项目 Skill 位于 [.agents/skills/embodied-paper-reader/](.agents/skills/embodied-paper-reader/SKILL.md)，配套[验收表](docs/acceptance.md)与本机 Zotero 脚本。OpenVLA 已用于验证正式版与 arXiv v3 的入库及重试。

## 请求方式

- **指定论文**。例如“帮我读 OpenVLA”。根据标题、作者、团队、日期或论文标识辨认目标。优先读你指定的版本；未指定时先复用库中已核实的全文。另行获取时优先正式出版版，其次采用最新可核实的 arXiv 修订。交付中文导读，并在本机 Zotero 的同一父条目下保存该版 PDF 和导读子笔记。
- **按主题找论文**。例如“从早到近梳理 VLA 的重要论文”。默认目标 6 篇，用户指定数量优先。记录实际检索来源、查询式、时间窗、截止日和筛选依据，在一张时间表里标出奠基工作、关键转折、期末代表及其证据。篇数不足或阶段缺失时，说明检索和排除过哪些工作、还有哪些缺口。用户选篇前，本次请求向 Zotero 新增 0 条记录。[固定时间窗的路线验收样例](docs/acceptance.md#route-example)

已有论文的找回可以直接问“我库里有 OpenVLA 吗”。只读返回书目、已核实版本、PDF 文件与笔记存在状态；用户选择精读或入库后再执行后续流程。路线模式的零新增由本次操作记录核验；库总数变化可能包含外部同步或手工操作，不能单独认定为本工作流的写入量。

查库输出包含核验时间和详单相对路径。每次查询在 `local/zotero-audit/` 单独保存带时间戳的记录，包括 PDF 检验与版本依据；后续连接失败也保留先前成功记录。

## 单篇交付

完整精读依次讲解**动机、架构、训练方式、数据集、训练与推理的信息流、完整例子**。训练阶段写明初始权重、数据、目标与参数更新范围；数据具体到一条样本；示例标明真实来源或教学性质。随后给出实验支持、适用边界、复现条件和默认 3 篇关联阅读。关键判断就近标出原文章节、图表或官方代码位置。

重要图表从同版 PDF 裁剪并放在相应讲解旁，保留必要图例、坐标与图注。脚本 `scripts/extract_figure.py` 输出图片及来源记录，使用约定见[精读结构与配图](.agents/skills/embodied-paper-reader/references/reading-guide.md)。图片展示在对话和本地导读中；当前 Zotero 同步提供含图号和原文链接的文本笔记，图片资源导入尚未实现。

中文导读用简短加粗突出研究问题、核心方法、主要结果、局限和复现门槛，方便快速扫读，每段优先突出 1–2 处。结果数字附近保留比较对象、任务范围和单位。对话使用 Markdown 加粗，Zotero 的 HTML 笔记使用 `<strong>`，让重点在两处都可见。

复现条件分推理、微调、仿真、真机四项。普通精读只整理官方条件。若你问“我的设备能跑吗”，优先用你在本轮给出的参数，其次用已有的 `local/device.md`。仅在目标确为当前电脑时，才对缺失参数做只读探测。缺少设备信息时，单列待验证的个人判断。

只有摘要时，只转述作者报告的事实和数字，不自行计算差值或排名。若原请求包含全文精读和入库，缺失的正文、PDF 或笔记列为待验证。具体判定见[核验表](docs/acceptance.md)。

## Zotero 中如何复读与复核

已有父条目和经核实的同版 PDF 可复用。导读标题带论文简称和版本，笔记头部标明取证日期、已核验内容及待补原因。同版摘要补成全文时更新原笔记，保留其 Key 和用户批注。已有笔记无法安全更新时报告待补。

首版脚本在一次执行中完成写前盘点、写入或更新、回读验证和写后盘点。重试从已落盘的记录和 Zotero 实际状态恢复。首版审计文件保存在 `local/zotero-audit/`，采用可跨平台使用的文件名。对话只展示脱敏结果、计数变化、核验时间和详单相对路径。

没有文本层的 PDF 可提供绑定原文件哈希的已复核 OCR 首页证据，由标准同步、查库和附件回读共用，保留原始 PDF 字节。字段见 [同步输入约定](.agents/skills/embodied-paper-reader/references/sync-input.md#无文本层-pdf)。

### 运行同步脚本

使用 Python 3.10+，打开 Zotero Desktop 10 并启用本机 API。在仓库根目录运行以下命令。第二次运行同步命令即可核验重试增量。

```powershell
python -m pip install -r requirements.txt
python -X utf8 scripts/zotero_sync.py "local/papers/<安全标识>/paper.json"
```

运行前将 `<安全标识>` 替换为实际目录名。新材料集中在 `local/papers/<安全标识>/`，包含清单、导读、内容核验及 `figures/` 裁图；字段与完整目录模板见 [Skill 同步输入约定](.agents/skills/embodied-paper-reader/references/sync-input.md)。`local/openvla/paper.json` 和 `publisher.json` 是本机早期 v3、正式版样品，路径继续有效。新检出的项目按 Skill 准备材料。

同步前可只读检查库内已有论文和版本，确认后导出已核实的 PDF 副本。

```powershell
python -X utf8 scripts/zotero_lookup.py "OpenVLA"
python -X utf8 scripts/zotero_lookup.py "OpenVLA" --export-version "arxiv:2406.09246v3"
```

脚本操作 Zotero Desktop 10 个人库。首次写入由 Zotero 弹窗授权，密钥默认保留在本次运行内存中；也可通过 `ZOTERO_LOCAL_API_KEY` 提供已取得的本地密钥。同步退出码 0 表示本机回读通过，内容事实按核验表另行验收。

运行本地隔离测试使用以下命令，测试以模拟库和临时文件验证同步行为。

```powershell
python -B -X utf8 -m unittest discover -s tests -v
```

## 使用项目 Skill

需要保存任务、查看阶段和中断续跑时，在 Codex 对话里说“用工作流帮我读某篇论文”或“用工作流查找 Zotero 中的 OpenVLA”。[Agent 工作流入口](docs/workflow.md)复用相同 Skill，默认由当前对话的 Agent 执行；桌面方式已跑通只读查库和同任务续跑。独立 CLI 后台方式及其当前环境限制见该文档。

在本仓库目录打开 Codex 新对话，输入“帮我读 OpenVLA”。也可显式输入“用 $embodied-paper-reader 帮我读 OpenVLA”。Skill 根据请求查找论文、核对版本、读取全文、生成带重点加粗的中文导读，再调用脚本同步到 Zotero。只请求摘要或选文时按对应范围交付。

Skill 引用仓库根目录脚本与核验表。[项目指引](AGENTS.md)将仓库内的论文查库、精读和路线请求接入本项目 Skill，配合 Zotero 插件完成连接诊断。

### 在其他项目中使用

Windows 上克隆完整仓库并安装 Python 依赖后，在仓库根目录运行一次用户级安装。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install_skill.ps1
```

安装脚本在用户目录的 `.agents/skills/embodied-paper-reader` 创建指向本仓库 Skill 的目录链接（Junction）。重复运行保留相同链接，已有其他文件或目录时停止并保留原内容。命令中的执行策略仅作用于本次 PowerShell 进程。脚本不修改全局提示词或 Zotero 设置，也不复制论文与审计。Codex 支持用户级 Skill 和链接目录，见 [OpenAI 官方说明](https://learn.chatgpt.com/docs/build-skills)。

安装后在其他项目的新对话输入“用 $embodied-paper-reader 查找我 Zotero 库中的 OpenVLA”。之后也可用自然语言触发。脚本、导读和审计仍使用原仓库，因此仓库需要保留在本机，移动后需重新设置链接。当前项目的文件访问和本机 API 权限仍适用；自动发现是否成功，以新对话实际载入本 Skill 为准。

2026-11-15 已在仓库外聊天中通过显式指定 `SKILL.md` 路径完成只读找回：返回书目、两版可用 PDF、笔记状态及零写入结果。该次请求未测试自然语言自动选择 Skill。

已在本机独立对话中验证自动触发、OpenVLA 已有版本复用、Octo 首次获取与入库、固定时间窗的六篇主题路线，以及选定 RT-2 v1 后的精读与入库。三篇单篇测试均取得重复执行零新增的记录。原文统计口径和未公开复现材料的缺项按核验表保留待验证。这些记录覆盖当前本机环境，其他 Zotero 版本与部署环境仍需实测。

本机可定位的入库记录包括 OpenVLA 正式版的 `local/zotero-audit/pmlr_v270_kim25c_bd2e1990cd9da2c6.json`、arXiv v3 的 `local/zotero-audit/arxiv_2406.09246v3.json` 和 RT-2 的 `local/zotero-audit/arxiv_2307.15818v1.json`。这些文件含个人库内部信息，受 Git 忽略，其他电脑在实测后生成自己的记录。

π₀ 的持久精读样品已验证正式版全文、六段图文、扫描件标准回读、导读原位更正和重试零新增；入库记录为 `local/zotero-audit/doi_10.15607_rss.2025.xxi.010_3dfd6f859c64a278.json`。正文与图示的复杂清台预训练归属存在未决对应，任务如实保留待补，不据此宣称严格未见任务迁移已证实。

固定时间窗的持久路线已通过干净上下文验证：重新执行 11 条查询，按 v1 日期整理 6 篇论文，记录 4 篇邻近工作的取舍，保存证据并完成任务，选篇前库写入为 0。范围为 2022 年至 2024-10-31；本机核验文件为 `local/routes/vla-2022-2024-10-31-forward-20261115T080337Z/verification.json`。该记录验证固定窗工作流，不代表已检索截至今天的全部重要工作。

## 开发进度

2026-11-14 的首版基线已达成。

1. 已完成 OpenVLA 单篇样品及版本、入库、重试核验。
2. 已完成项目级 Codex Skill 封装，并按独立对话反馈修订。
3. 已完成固定时间窗的主题路线测试，覆盖排序、阶段角色和选篇前零写入。
4. 已完成 Octo、RT-2 v1 的独立对话测试与路线选篇衔接；中断补缺、人工修改保护等行为由隔离测试覆盖。

2026-11-15 的六段式精读与配图改版已完成本机独立对话验收，覆盖实际看图、同版导读原位更新与重试零新增；只读找回也已通过入口触发、状态完整性与脱敏复测。Windows 用户级链接安装入口已提供，跨项目显式调用已验证。桌面 Agent 工作流已覆盖只读任务、同任务续跑、π₀ 精读入库和固定窗持久路线。CLI 后台方式仍受 Windows 子进程启动问题影响。论文自身的未决证据继续按项标注。后续按真实主题及更宽时间窗扩展选文覆盖，再按需要演进 Zotero 笔记内嵌图片和其他 Zotero 版本的兼容性。

Git 跟踪工作流规则、脚本和测试用例。论文 PDF、个人导读和 Zotero 数据保存在本机。需要暂存的阅读材料可放在仓库中由 Git 忽略的 `local/` 目录。
