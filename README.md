# laoke-kb-architect · 知识库搭建助手

> 局内人·老K · 专注实体老板 AI 落地实战

把长篇素材（文章、笔记、访谈稿、产品文档、研报）按标题层级切成结构化知识条目，自动生成分类、标签、摘要与去重指纹，配套信息架构、分块策略、条目模板与入库质检方法论。不止「切一刀」，更帮你建对、建干净、建完真能用。

## 这个 Skill 能做什么

- **长文切片**：按 H2/H3 标题层级与语义边界，把一份长文切成多条独立知识条目。
- **自动元数据**：每条自动推导 `category` / `tags` / `summary` / `source` / `fingerprint`。
- **结构化输出**：每条写成带 YAML frontmatter 的 `.md`，外加 `manifest.json` 索引，直接可进 ima 知识库 / 向量库 / 笔记。
- **方法论配套**：信息架构、分块粒度、条目模板、入库质检清单。
- **内置脚本**：`scripts/kb_chunk.py`（纯标准库，零依赖，含 `--selftest`）。

## 快速开始

```bash
python scripts/kb_chunk.py --input 素材.md --out ./entries --title "产品帮助中心" --tags "产品,帮助中心,FAQ" --max-chars 1800
```

输出 `./entries/` 下多条 `.md` + `manifest.json`。脚本自检：`python scripts/kb_chunk.py --selftest`。

## 目录结构

- `SKILL.md` —— 完整使用说明与方法论
- `references/` —— 知识管理体系 / 信息架构 / 分块策略 / 条目模板 / 质量清单（5 篇）
- `scripts/kb_chunk.py` —— 切片与结构化脚本
- `hooks/guardrail.md` —— 合规护栏

## 相关资源

- ima 知识库《局内人·老K · AI 落地实战库》：收录 WorkBuddy 实战案例 200+ 与各类提效 Skill 用法
- ima 知识库《WorkBuddy 官方实战案例 200+》：大量「资料结构化沉淀」实战样例
- 作者落地页：https://muzhi-888.github.io/ju-nei-ren-lao-k/
- SkillHub 作者主页：搜索「局内人·老K」

## License

MIT —— 可自由使用、修改、再分发，请保留作者署名。

## 免责声明

本工具仅供学习与研究使用，用来整理你有权处理的资料。生成内容不构成任何投资、法律或商业建议；涉及隐私数据与第三方版权内容，请遵守相关法律法规与平台规范。
