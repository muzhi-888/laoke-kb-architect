# -*- coding: utf-8 -*-
"""
kb_chunk.py —— 知识库条目切片与结构化工具（纯标准库，零依赖）

功能：
  把一份长篇 Markdown / 纯文本素材（文章、笔记、访谈稿、产品文档、研报）
  按「标题层级 + 语义边界」切成适合入库的知识条目，并为每条自动生成
  结构化元数据（标题 / 分类 / 标签 / 摘要 / 来源 / 指纹），输出：
    - 独立条目文件  <slug>.md   （带 YAML frontmatter，直接可进 ima / 向量库 / 笔记）
    - manifest.json  （全量索引，含去重指纹，便于增量更新）

设计原则：
  - 零依赖：只用 argparse / re / os / json / hashlib / datetime / html。
  - 确定性：同一输入 + 同一参数 => 同一输出（slug 稳定、可重跑）。
  - 安全：不联网、不执行外部命令、不删除任何文件。

用法：
  python kb_chunk.py --input 素材.md --out ./entries --title "产品手册"
  python kb_chunk.py --input 素材.md --out ./entries --max-chars 1800 --tags 产品,FAQ
  python kb_chunk.py --selftest        # 内置自检，exit 0 即通过
"""
import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def slugify(text, used):
    """把任意标题转成稳定、合法的条目 slug（ASCII 安全 + 中文保真）。"""
    raw = text.strip().replace("\n", " ").replace("\r", " ")
    # 去掉文件名非法字符
    raw = re.sub(r'[\\/:*?"<>|#]', "", raw)
    raw = re.sub(r"\s+", "-", raw)
    raw = raw.strip("-").strip()
    if not raw:
        raw = "untitled"
    base = raw[:48]
    slug = base
    n = 1
    while slug in used:
        n += 1
        slug = f"{base}-{n}"
    used.add(slug)
    return slug


def clean_text(s):
    s = re.sub(r"\r\n", "\n", s)
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def extract_summary(body, n=160):
    """从正文取前 n 个非标点字符作为摘要。"""
    txt = re.sub(r"[#>*`\-•\-\u2022\s]", "", body)
    txt = re.sub(r"[#*`>\-]", "", body)
    # 去掉 markdown 符号后取纯文字
    plain = re.sub(r"[#*>`_\-\[\]()！？。，、；：]", "", body)
    plain = plain.replace("\n", " ").strip()
    # 优先取第一段实质文字
    first = re.split(r"\n\s*\n", body.strip())[0]
    first_plain = re.sub(r"[#*>`_\-]", "", first)
    first_plain = first_plain.replace("\n", " ").strip()
    pick = first_plain if len(first_plain) >= 20 else plain
    if len(pick) <= n:
        return pick
    return pick[:n].rstrip() + "…"


def derive_tags(hierarchy, extra_tags, body):
    """由标题路径 + 显式标签 + 正文关键词推断标签。"""
    tags = set()
    for h in hierarchy:
        # 取标题里的实词（去掉停用词）
        words = re.findall(r"[一-龥A-Za-z0-9]{2,}", h)
        stop = {"我们", "他们", "这个", "那个", "以及", "或者", "关于", "如何", "什么",
                "怎么", "为什么", "因为", "所以", "但是", "并且", "如果", "可以", "需要",
                "一个", "一种", "这些", "那些", "以及", "进行", "通过", "对于", "说明"}
        for w in words:
            if w not in stop and len(w) >= 2:
                tags.add(w)
    for t in extra_tags:
        t = t.strip()
        if t:
            tags.add(t)
    # 正文高频词补充（取出现 >=3 次的两字以上中文词，作为补充标签）
    counter = {}
    for m in re.findall(r"[一-龥]{2,4}", body):
        counter[m] = counter.get(m, 0) + 1
    for w, c in counter.items():
        if c >= 4 and len(tags) < 10:
            tags.add(w)
    return sorted(tags)[:12]


def split_paragraphs(text):
    # 按空行分段，保留结构
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


# ---------------------------------------------------------------------------
# 核心切片逻辑
# ---------------------------------------------------------------------------

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)


def chunk_markdown(md_text, max_chars=1800, extra_tags=None):
    """按 H2 切块；超长块再按 H3 / 段落切；返回条目列表。"""
    extra_tags = extra_tags or []
    lines = md_text.split("\n")
    # 找到所有标题位置
    headings = []  # (level, title, line_index)
    for i, line in enumerate(lines):
        m = HEADING_RE.match(line)
        if m:
            headings.append((len(m.group(1)), m.group(2).strip(), i))

    # 顶层分类（第一个 H1，若没有则用文件名/标题）
    top_category = "未分类"
    for lvl, title, idx in headings:
        if lvl == 1:
            top_category = title
            break

    entries = []
    used = set()

    # 若完全没有标题，整篇当一个条目
    if not headings:
        body = clean_text(md_text)
        title = "全文"
        slug = slugify(title, used)
        tags = derive_tags([], extra_tags, body)
        entries.append({
            "slug": slug,
            "title": title,
            "category": top_category,
            "hierarchy": [],
            "tags": tags,
            "summary": extract_summary(body),
            "body": body,
        })
        return entries

    # 以 H2 为一级切分单元
    h2_list = [(lvl, title, idx) for (lvl, title, idx) in headings if lvl == 2]
    if not h2_list:
        # 没有 H2，用 H1 / H3 兜底
        h2_list = [(lvl, title, idx) for (lvl, title, idx) in headings if lvl in (1, 3)]
    if not h2_list:
        h2_list = headings

    for k, (lvl, title, idx) in enumerate(h2_list):
        start = idx + 1
        end = h2_list[k + 1][2] if k + 1 < len(h2_list) else len(lines)
        block_lines = lines[start:end]
        block_text = clean_text("\n".join(block_lines))
        hierarchy = [title]

        # 超长块：尝试按 H3 再切
        if len(block_text) > max_chars:
            sub = HEADING_RE.findall("\n".join(block_lines))
            sub_h3 = [(len(g), t.strip(), None) for (g, t) in sub if len(g) >= 3]
            if len(sub_h3) >= 2:
                # 用 H3 切
                sub_positions = []
                for j, bl in enumerate(block_lines):
                    m = HEADING_RE.match(bl)
                    if m and len(m.group(1)) >= 3:
                        sub_positions.append((m.group(2).strip(), j))
                for si, (st, sj) in enumerate(sub_positions):
                    s_start = sj + 1
                    s_end = sub_positions[si + 1][1] if si + 1 < len(sub_positions) else len(block_lines)
                    s_body = clean_text("\n".join(block_lines[s_start:s_end]))
                    if not s_body:
                        continue
                    s_title = st
                    s_slug = slugify(f"{title}-{s_title}", used)
                    s_tags = derive_tags([title, s_title], extra_tags, s_body)
                    entries.append({
                        "slug": s_slug, "title": s_title, "category": top_category,
                        "hierarchy": [title, s_title], "tags": s_tags,
                        "summary": extract_summary(s_body), "body": s_body,
                    })
                continue

        # 仍然超长（无 H3）：按段落切，尽量接近 max_chars
        if len(block_text) > max_chars:
            paras = split_paragraphs(block_text)
            buf = ""
            part = 0
            for p in paras:
                if len(buf) + len(p) + 2 <= max_chars:
                    buf = (buf + "\n\n" + p).strip()
                else:
                    if buf:
                        part += 1
                        pslug = slugify(f"{title}-{part}" if part > 1 else title, used)
                        ptags = derive_tags(hierarchy, extra_tags, buf)
                        entries.append({
                            "slug": pslug, "title": title + (f"（{part}）" if part > 1 else ""),
                            "category": top_category, "hierarchy": list(hierarchy),
                            "tags": ptags, "summary": extract_summary(buf), "body": buf,
                        })
                    buf = p
            if buf:
                part += 1
                pslug = slugify(f"{title}-{part}" if part > 1 else title, used)
                ptags = derive_tags(hierarchy, extra_tags, buf)
                entries.append({
                    "slug": pslug, "title": title + (f"（{part}）" if part > 1 else ""),
                    "category": top_category, "hierarchy": list(hierarchy),
                    "tags": ptags, "summary": extract_summary(buf), "body": buf,
                })
            continue

        # 正常块
        slug = slugify(title, used)
        tags = derive_tags(hierarchy, extra_tags, block_text)
        entries.append({
            "slug": slug, "title": title, "category": top_category,
            "hierarchy": list(hierarchy), "tags": tags,
            "summary": extract_summary(block_text), "body": block_text,
        })

    return entries


def write_entries(entries, out_dir, source_name):
    os.makedirs(out_dir, exist_ok=True)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source_name,
        "count": len(entries),
        "entries": [],
    }
    for e in entries:
        fingerprint = hashlib.sha1((e["title"] + "|" + e["body"][:200]).encode("utf-8")).hexdigest()[:12]
        fm = f"""---
slug: {e['slug']}
title: {e['title']}
category: {e['category']}
tags: {', '.join(e['tags'])}
summary: {e['summary']}
source: {source_name}
fingerprint: {fingerprint}
---

# {e['title']}

{e['body']}
"""
        path = os.path.join(out_dir, e["slug"] + ".md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(fm)
        manifest["entries"].append({
            "slug": e["slug"], "title": e["title"], "category": e["category"],
            "tags": e["tags"], "summary": e["summary"], "fingerprint": fingerprint,
            "file": e["slug"] + ".md",
        })
    mp = os.path.join(out_dir, "manifest.json")
    with open(mp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return mp


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------

SAMPLE = """# 产品帮助中心

## 账号与登录

### 如何注册账号
打开官网点击右上角「注册」，使用手机号或邮箱即可注册。注册后需通过验证码完成实名校验。一个手机号只能绑定一个主账号。

### 忘记密码怎么办
在登录页点击「忘记密码」，通过短信验证码重置。若手机号已停用，需联系人工客服提交身份材料解绑。

## 会员与计费

### 会员有哪些档位
会员分为基础版、专业版、旗舰版三档。基础版免费，专业版 39 元/月，旗舰版 99 元/月。年付享受 8 折。

### 怎么开发票
在「我的-账单」页点击「申请发票」，填写抬头与税号后提交，电子发票 1-3 个工作日开具并发送至邮箱。

## 数据安全

### 我的数据安全吗
平台采用传输加密与存储加密，敏感字段脱敏处理。数据所有权归用户，可随时导出或删除。
"""


def selftest():
    import tempfile
    tmp = tempfile.mkdtemp(prefix="kb_selftest_")
    sample_path = os.path.join(tmp, "sample.md")
    with open(sample_path, "w", encoding="utf-8") as f:
        f.write(SAMPLE)
    out_dir = os.path.join(tmp, "entries")
    entries = chunk_markdown(SAMPLE, max_chars=1800, extra_tags=["产品", "帮助中心"])
    if len(entries) < 3:
        print(f"[FAIL] 切片数量过少: {len(entries)}")
        return 1
    mp = write_entries(entries, out_dir, "sample.md")
    # 校验产物
    files = os.listdir(out_dir)
    md_files = [x for x in files if x.endswith(".md")]
    if len(md_files) < 3:
        print(f"[FAIL] 条目文件过少: {len(md_files)}")
        return 1
    if "manifest.json" not in files:
        print("[FAIL] 缺少 manifest.json")
        return 1
    # 校验 frontmatter 完整
    for fn in md_files:
        with open(os.path.join(out_dir, fn), encoding="utf-8") as f:
            c = f.read()
        for field in ("slug:", "title:", "category:", "tags:", "summary:", "source:", "fingerprint:"):
            if field not in c:
                print(f"[FAIL] {fn} 缺少字段 {field}")
                return 1
    # 校验去重（slug 唯一）
    slugs = [e["slug"] for e in entries]
    if len(slugs) != len(set(slugs)):
        print("[FAIL] slug 重复")
        return 1
    print(f"[OK] 自检通过：生成 {len(md_files)} 个条目 + manifest.json")
    print(f"     样例条目：{', '.join(slugs[:5])}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="知识库条目切片与结构化工具")
    ap.add_argument("--input", help="输入 Markdown / 文本文件路径")
    ap.add_argument("--out", help="输出目录（条目 .md + manifest.json）")
    ap.add_argument("--title", default="", help="来源标题（写入 source 字段）")
    ap.add_argument("--max-chars", type=int, default=1800, help="单条最大字符数（默认 1800）")
    ap.add_argument("--tags", default="", help="额外标签，逗号分隔")
    ap.add_argument("--selftest", action="store_true", help="运行内置自检并退出")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(selftest())

    if not args.input or not args.out:
        ap.error("--input 与 --out 必须同时提供（或使用 --selftest）")

    if not os.path.isfile(args.input):
        print(f"[ERROR] 输入文件不存在: {args.input}")
        sys.exit(2)

    with open(args.input, encoding="utf-8") as f:
        md = f.read()
    extra = [t for t in args.tags.split(",") if t.strip()]
    entries = chunk_markdown(md, max_chars=args.max_chars, extra_tags=extra)
    src = args.title or os.path.basename(args.input)
    mp = write_entries(entries, args.out, src)
    print(f"[DONE] 共切片 {len(entries)} 条，输出至 {args.out}")
    print(f"       索引文件: {mp}")


if __name__ == "__main__":
    main()
