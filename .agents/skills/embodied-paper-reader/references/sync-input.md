# 同步输入约定

从 Skill 所在仓库根目录运行脚本。这里描述脚本实际接受的字段，验收判据见根目录 docs/acceptance.md。

## 清单字段

| 字段 | 填写规则 |
| --- | --- |
| canonical | 包含论文与所选版本的规范标识，如 arxiv:2406.09246v3、doi:10.1234/example@vor、pmlr:v270/kim25c@vor。 |
| version | arXiv 用 2406.09246v3；正式版与 canonical 相同。用于匹配笔记首行括号。 |
| source | 实际读取的版本化 HTML、摘要记录或该篇出版记录。arXiv 限 arxiv.org 的 /html/、/abs/、/pdf/ 版本化地址。 |
| pdf_url | 实际取得该版 PDF 的来源地址。 |
| aliases | 跨出版形态查重线索，数组，至少包含已核实的 arXiv ID、DOI 或出版记录 URL。 |
| title、short_title | 原文完整标题与可读简称。 |
| authors | 按当前版本作者顺序填全，每项为“名 姓”。当前脚本按最后一个空格拆姓氏，复姓或团体作者需核实表示及查重结果。 |
| date | 本版本日期或正式出版年，首次公开日期另记导读。 |
| entry | Zotero 字段字典。预印本用 itemType=preprint，正式会议论文用 conferencePaper。字段名按 Zotero 类型填写，如 repository、url、archiveID、proceedingsTitle、pages、volume、publisher。复用已有父项时保留其书目信息。 |
| pdf、note | 相对于清单目录的 PDF 与导读 HTML 文件名。 |
| pdf_sha256 | 正式版必填，从该篇出版记录链接取得的 PDF 文件 SHA-256。哈希与来源证据共同确定版本。 |

先按身份与版本选定材料再填写清单。文件名使用便于跨平台的 ASCII 安全标识。

## 笔记和内容核验

HTML 以 `<h1>[embodied-paper-reader] 中文导读 · 简称 (version)</h1>` 起始。正文使用 p、h2、ul/li、a 与 strong 即可。导读头部包含实际版本、选版依据、取证日、内容核验状态和待补原因。关键数字在对应句末定位到该版章节或图表。

在清单旁保存 acceptance.md，逐项填写根目录核验表的状态与实际读取证据。父条目及两个子项的实测由同步审计补充；正文事实由 Agent 对照一手材料核验。只有摘要时仍可保存概览，当前同步脚本需要 PDF，缺 PDF 的入库标待验证。

## 查库和同步结果

`zotero_lookup.py` 的 verified_version 来源为本机已通过审计的 PDF 哈希，或与父条目标题一致的 PDF 首页 arXiv 版本标记。未知正式版可按出版记录与文件哈希另行核验。导出副本位于 local/papers/ 下，文件名含哈希，用户随后可用该文件准备清单。

`zotero_sync.py` 按标识符、归一化标题加第一作者查重。每版审计保留运行历史、父子关系、PDF 哈希及笔记写入哈希。失败或中断后先查本机记录与实际对象，再运行同一清单补缺。沿用审计原样恢复，核对三个 Key 及计数。输出的 0/0/0 表示三类对象均无新增，更新笔记内容仍可能发生。

本地 API 授权密钥默认只保留在一次脚本进程内。ZOTERO_LOCAL_API_KEY 可传入已取得的本地密钥；账户网页 API 密钥与本地密钥用途不同。
