# 同步输入约定

从 Skill 所在仓库根目录运行脚本。这里描述脚本实际接受的字段，验收判据见根目录 docs/acceptance.md。

## 清单字段

| 字段 | 填写规则 |
| --- | --- |
| canonical | 包含论文与所选版本的规范标识，如 arxiv:2406.09246v3、doi:10.1234/example@vor、pmlr:v270/kim25c@vor。 |
| version | arXiv 用 2406.09246v3；正式版与 canonical 相同。用于匹配笔记首行括号。 |
| source | 实际读取的版本化 HTML、摘要记录或该篇出版记录。arXiv 接受 arxiv.org 的 /html/、/abs/、/pdf/ 版本化地址，包含 /pdf/2406.09246v3.pdf 这样的 PDF 后缀形式。 |
| pdf_url | 实际取得该版 PDF 的来源地址。 |
| aliases | 跨出版形态查重线索，数组，至少包含已核实的 arXiv ID、DOI 或出版记录 URL。 |
| title、short_title | 原文完整标题与可读简称。 |
| authors | 字符串列表，按当前版本作者顺序填全，每项为“名 姓”。查库兼容单字段个人作者 name，按末词兜底比较姓氏；写入仍按最后一个空格拆姓氏，复姓或团体作者需核实表示及查重结果。 |
| date | 本版本日期或正式出版年，首次公开日期另记导读。 |
| entry | Zotero 字段字典。预印本用 itemType=preprint，正式会议论文用 conferencePaper。字段名按 Zotero 类型填写，如 repository、url、archiveID、proceedingsTitle、pages、volume、publisher。复用已有父项时保留其书目信息。 |
| pdf、note | 相对于清单目录的 PDF 与导读 HTML 文件名。 |
| pdf_sha256 | 正式版必填，从该篇出版记录链接取得的 PDF 文件 SHA-256。哈希与来源证据共同确定版本。 |
| pdf_text_evidence | 可选，无文本层 PDF 的已复核首页证据 JSON，相对于清单目录。字段及用法见下文。 |

先按身份与版本选定材料再填写清单。文件名使用便于跨平台的 ASCII 安全标识。

清单顶层为 JSON 对象。authors 和 aliases 使用字符串列表，entry 使用包含非空字符串 itemType 的对象，其余必填字段使用非空字符串。正式版另需 pdf_sha256。字段缺失或类型不合适时，在访问 Zotero 前报告待补。

## 无文本层 PDF

实际查看原页并复核 OCR 首页后，可在清单中加 `"pdf_text_evidence": "pdf-text-evidence.json"`。证据文件包含四个非空字符串字段：

```json
{
  "source_pdf_sha256": "<原始PDF的完整SHA-256>",
  "first_page_text": "<已对照原页复核的首页文本>",
  "method": "<OCR工具与目视复核方法>",
  "reviewed_at": "2026-11-15"
}
```

只有原生提取为空时才使用该证据，哈希必须与当前 PDF 完全一致；标题、第一作者和版本继续按原有规则核验。标准同步在身份与版本核验后，将该文字证据按 PDF 哈希缓存在本机审计目录。后续同步、查库和本地附件回读可以复用相同字节的证据，无需替换 PDF 库方法或重新生成 PDF。文件不同或证据不足时记待验证。脚本不自动运行 OCR，也不宣称能仅靠文本记录证明已目视检查；正文和关键图表仍由 Agent 实际查看。

## 本地工作目录

新材料统一放在 `local/papers/<安全标识>/`，例如 `local/papers/arxiv_2307.15818v1/`。安全标识包含论文和版本，避免 Windows 文件名中的斜杠、冒号等特殊字符。沿用旧样品与共享的 PDF 时，清单可用相对路径引用已有材料，无需搬动或复制。

```text
local/papers/<安全标识>/
  paper.json       同步清单
  paper.pdf        该版 PDF，也可由清单引用已有文件
  guide.html       本地图文导读
  guide.md         需要 Markdown 时导出
  note.html        单独准备入库文本时使用
  acceptance.md    本轮内容核验
  figures/
    figure-2.png
    figure-2.json  图片来源、版本、页码与裁剪坐标
```

路线记录留在 `local/routes/`，同步和查库详单留在 `local/zotero-audit/`。`local/openvla/` 属于早期样品目录，现有路径继续有效。

## 笔记和内容核验

HTML 主标题采用 `<h1>[embodied-paper-reader] 中文导读 · 简称 (version)</h1>`。可提供片段或包含 head/title/body 的完整文档；同步时读取 h1 并提取 body 正文。无 h1 时回退到正文首个非空文本行。正文使用 p、h2、ul/li、a 与 strong 即可。导读头部包含实际版本、选版依据、取证日、内容核验状态和待补原因。关键数字在对应句末定位到该版章节或图表。

完整精读内容采用[精读结构与配图](reading-guide.md)的六段讲解顺序。带裁图的本地 HTML 与用于 Zotero 同步的笔记可分别保存，清单的 note 指向后者。当前脚本上传 PDF 与笔记正文；本地相对图片引用须转换成原文图号、说明和一手链接，再准备同步清单。

在清单旁保存 acceptance.md，逐项填写根目录核验表的状态与实际读取证据。父条目及两个子项的实测由同步审计补充；正文事实由 Agent 对照一手材料核验。只有摘要时仍可保存概览，当前同步脚本需要 PDF，缺 PDF 的入库标待验证。

## 查库和同步结果

`zotero_lookup.py` 的 verified_version 来源为本机已通过审计的 PDF 哈希，或与父条目标题一致的 PDF 首页 arXiv 版本标记。未知正式版可按出版记录与文件哈希另行核验。导出副本位于 local/papers/ 下，文件名含哈希，用户随后可用该文件准备清单。

标准 arXiv ID、DOI 和 URL 按父条目的标识元数据匹配，覆盖 Extra 中的已核实别名；普通标题线索使用 Zotero 查询。仅用编号查询为空不足以认定论文不在库中，未核实身份时还需按标题复查。

只读找回也使用此入口。返回的 file_available 表示该附件本地文件可用；has_notes 表示父条目下存在笔记，workflow_note_count 只统计本工作流固定标记的笔记。它们用于定位资料，笔记内容正确性仍需另行回读核验。

`zotero_sync.py` 按标识符、归一化标题加第一作者查重。每版审计保留运行历史、父子关系、PDF 哈希及笔记写入哈希。失败或中断后先查本机记录与实际对象，再运行同一清单补缺。沿用审计原样恢复，核对三个 Key 及计数。输出的 0/0/0 表示三类对象均无新增，更新笔记内容仍可能发生。

Windows 上选择“始终允许 / Always Allow”取得的本地 API 密钥保存在系统凭据管理器，按稳定的 Zotero Server ID 分开，跨脚本进程复用；单次授权不保存。收到401时清除失效缓存，重新授权后仅重试一次，其他HTTP错误不自动重新授权。可用 `zotero_sync.py --authorize` 提前授权，`--forget-authorization` 清除当前实例缓存。读取库不访问凭据存储。系统凭据不可用时仅在进程内使用，不回退到明文文件。其他系统目前不持久化。

ZOTERO_LOCAL_API_KEY 仍可显式传入密钥，优先于缓存且不代为保存；该显式密钥失效时报告错误，由用户更新。账户网页 API 密钥与本地密钥用途不同。密钥不进入审计、仓库或工具输出。
