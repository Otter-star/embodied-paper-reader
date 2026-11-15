# 给安装 Agent 的说明

用户可以只发送：

> 帮我安装这个工作流：https://github.com/Otter-star/embodied-paper-reader

安装目标是让后续对话能调用完整的论文阅读流程。**保留完整仓库、安装 Python 依赖，并把仓库内的 Skill 链接到用户级发现目录。** 本 Skill 使用外层的 `scripts/`、`docs/` 和 `requirements.txt`，不能仅用通用 Skill 安装器复制 `.agents/skills/embodied-paper-reader/`。

## 环境与范围

- 当前安装脚本与实测环境为 **Windows、Codex、Python 3.10+、Git、Zotero Desktop 10 个人库**。Agent 需要本机文件与命令执行能力；阅读时还需要联网检索及看图能力。其他 Agent 或系统须按各自的 Skill 发现规则接入，尚未验收，不能仅凭复制成功报告可用。
- Zotero 插件是可选诊断工具。本仓库脚本直接使用 Zotero 本机 API，无需额外配置云端服务或模型 API Key。模型由当前 Agent 提供。
- 私有仓库使用现有 Git 登录权限；无法访问时报告需要仓库授权，不要求用户把令牌贴到对话里。缺 Git、Python 或 Zotero 时说明缺项，按用户环境安装或由用户补齐，不把 Skill 链接成功当作环境已就绪。
- 安装只配置本工作流，不读取论文库、不导入示例论文、不请求 Zotero 写入授权，也不修改全局 Agent 指令、权限或 Zotero 设置。

## Windows 安装步骤

1. 先读取仓库 `README.md` 和本文件。将完整仓库保存在用户可长期保留的位置，默认可用 `%USERPROFILE%\agent-workflows\embodied-paper-reader`。已有同名工作目录时先检查来源及修改，复用正确仓库，不覆盖其他内容。
2. 检查 Git 与 Python 3.10+，克隆仓库后运行下列安装命令。命令中的执行策略只作用于本次 PowerShell 进程；若机器策略拒绝执行，按环境的正常授权机制处理。

```powershell
$paperReaderRoot = Join-Path $env:USERPROFILE 'agent-workflows\embodied-paper-reader'
git clone https://github.com/Otter-star/embodied-paper-reader.git "$paperReaderRoot"
Set-Location -LiteralPath $paperReaderRoot
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install_skill.ps1 -InstallDependencies
```

上述克隆命令只用于目标尚不存在时。若需指定 Python 解释器，例如已有的虚拟环境，向安装脚本传入 `-PythonExecutable '解释器绝对路径'`。后续阅读命令也使用同一解释器。脚本默认调用 `python`，不更改全局 Python 配置。包源无法提供依赖时，可单次使用官方 PyPI 重试，不修改全局 pip 源：

```powershell
python -m pip install --index-url https://pypi.org/simple -r requirements.txt
```

3. 核验用户级 `~/.agents/skills/embodied-paper-reader` 链接解析后的 `SKILL.md` 指向该仓库，并能访问仓库的 `scripts/zotero_sync.py`、`scripts/paper_workflow.py` 和 `docs/acceptance.md`。重复安装同一链接应成功；目标是别的文件、目录或链接时保留原内容并报告冲突。
4. 若 Zotero 已启动，可只读请求 `http://127.0.0.1:23119/api/` 检查连接，只报告 HTTP 状态，不输出响应头或实例标识。连接被执行权限阻止时先按工具机制申请本机访问权限。未启动、未启用 API 或版本不足时，分别报告待配置；Skill 可先安装，不能报告 Zotero 已可用。没有必要为了安装运行查库或同步命令。
5. 交付安装位置、依赖检查结果、Skill 链接结果及 Zotero 连接状态。说明 Skill 在后续对话中使用；若未被发现，重新打开对话后显式调用 `$embodied-paper-reader`。磁盘链接核验不等于已经验证客户端自动发现。

## 安装后的用法

用户不需要背固定提示词，例如：

- `帮我读 OpenVLA`：默认全文精读、同版 PDF 和 Zotero 中文导读。
- `用工作流精读 π₀，并存入 Zotero`：在同样规则下保存任务、阶段与核验结果。
- `我 Zotero 库里有 OpenVLA 吗`：只读找回已有版本与 PDF、笔记状态。
- `从早到近梳理机器人操控 VLA 的重要论文`：先给路线，用户选篇前不入库。
- `继续上次的论文工作流`：先定位该仓库 `local/workflows/` 中的原任务；有多个候选且无法区分时再询问。

可在其他项目使用用户级 Skill，仓库仍需留在本机。文件访问和本机 API 仍受当前 Agent 的权限范围约束。首次实际写入时，在 Zotero 选择“始终允许 / Always Allow”，Windows 系统凭据管理器会供后续进程复用；安装本身不触发这个窗口。密钥不写仓库、审计、日志或对话。

## 更新与移除

更新时先检查仓库状态，在工作区干净时执行 `git pull --ff-only`，再运行 `scripts/install_skill.ps1 -InstallDependencies`。链接会沿用新文件，已有 `local/` 阅读材料与审计继续留在本机。存在本地修改或来源不同的同名安装时先报告情况，不执行重置或删除。

移除 Skill 时只移除已经确认的用户级链接，保留完整仓库和个人材料。`scripts/zotero_sync.py --forget-authorization` 可清除当前 Zotero 实例在本工作流中的凭据缓存；Zotero 设置→高级中的“清除写入授权”可撤销 Zotero 侧授权。移除链接不自动清除这些数据。
