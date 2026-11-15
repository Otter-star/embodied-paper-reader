# 论文阅读项目指引

用户请求安装、更新或分享此工作流时，先读取 [INSTALL.md](INSTALL.md)。完整仓库、Python 依赖和用户级 Skill 链接均须核验，安装阶段不读取或写入论文库。

在本仓库处理论文查找、精读、主题路线，以及“我的 Zotero 库里有某篇论文吗”等库内找回请求时，先读取 [.agents/skills/embodied-paper-reader/SKILL.md](.agents/skills/embodied-paper-reader/SKILL.md)，按本项目的交付范围与核验表执行。

库内找回使用本仓库的 scripts/zotero_lookup.py，返回书目、版本、PDF 与笔记状态。Zotero 插件可用于连接诊断，调用及输出遵循项目 Skill 的脱敏约定。含内部 Key、配置路径、附件存储路径或原始响应的详单保存在被 Git 忽略的 local/，对话和工具输出使用脱敏结果。
