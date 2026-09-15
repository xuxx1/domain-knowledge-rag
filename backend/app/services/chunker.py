"""文本分块服务（优化版）

策略：标题/段落优先 + 语义完整 + 滑动窗口
1. 先识别 Markdown 标题（#、##、###）作为切分锚点，标题随其后内容保留为上下文前缀；
2. 无标题的文本按自然段（空行分隔）划分；
3. 优先将相邻段落合并到接近 CHUNK_SIZE（默认 700），尽量不打断段落；
4. 单段/单节超过上限时，按句子边界硬切，保留 CHUNK_OVERLAP 重叠（默认 120）；
5. 每个 chunk 尽量带上所属标题作为前缀，提升检索语义。

约定：目标块 CHUNK_SIZE，重叠 CHUNK_OVERLAP。此处只返回文本列表，chunk_id 由调用方分配。
"""

import re

from .. import config

# 中文句末标点 + 英文句末标点
_SENTENCE_END = re.compile(r"(?<=[。！？!?；;\n])")
# Markdown 标题行
_MD_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*$")

_DEFAULT_CHUNK_SIZE = 700
_DEFAULT_OVERLAP = 120


def _split_sentences(paragraph: str) -> list[str]:
    parts = _SENTENCE_END.split(paragraph)
    return [p for p in parts if p.strip()]


def _hard_split(paragraph: str, chunk_size: int, overlap: int) -> list[str]:
    """超长段落/节：优先按句子边界切，切不动再按字符硬切"""
    sentences = _split_sentences(paragraph)
    if len(sentences) <= 1:
        step = max(chunk_size - overlap, 1)
        return [
            paragraph[i : i + chunk_size]
            for i in range(0, len(paragraph), step)
        ]
    chunks: list[str] = []
    current = ""
    for sent in sentences:
        if len(sent) > chunk_size * 1.5:
            if current.strip():
                chunks.append(current.strip())
                current = ""
            chunks.extend(_hard_split(sent, chunk_size, overlap))
            continue
        if current and len(current) + len(sent) > chunk_size:
            chunks.append(current.strip())
            current = current[-overlap:] if overlap > 0 else ""
        current += sent
    if current.strip():
        chunks.append(current.strip())
    return chunks


def _is_heading(line: str) -> bool:
    return bool(_MD_HEADING.match(line))


def _strip_heading(line: str) -> str:
    return _MD_HEADING.sub("", line).strip()


def chunk_text(
    text: str,
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> list[str]:
    """主入口：返回分块列表"""
    chunk_size = chunk_size or getattr(config, "CHUNK_SIZE", _DEFAULT_CHUNK_SIZE)
    overlap = overlap or getattr(config, "CHUNK_OVERLAP", _DEFAULT_OVERLAP)
    if overlap >= chunk_size:
        raise ValueError("overlap 必须小于 chunk_size")

    # 按 Markdown 标题切成"节"（每节保留标题），无标题则整段为节
    lines = text.splitlines()
    sections: list[str] = []
    cur: list[str] = []
    for ln in lines:
        if _is_heading(ln):
            if cur:
                sections.append("\n".join(cur))
                cur = []
        cur.append(ln)
    if cur:
        sections.append("\n".join(cur))
    sections = [s for s in sections if s.strip()]

    chunks: list[str] = []
    for sec in sections:
        chunks.extend(_chunk_section(sec, chunk_size, overlap))
    return [c for c in chunks if len(c.strip()) >= 10]


def _chunk_section(section: str, chunk_size: int, overlap: int) -> list[str]:
    """把一节文本（可能含标题）按自然段合并成块，标题作为块前缀"""
    lines = section.splitlines()
    # 分离标题行与非标题内容
    heading = ""
    body_lines = []
    for ln in lines:
        if _is_heading(ln) and not heading:
            heading = _strip_heading(ln)
        else:
            body_lines.append(ln)
    body = "\n".join(body_lines)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    if not paragraphs:
        return [f"# {heading}"] if heading else []

    prefix = f"{heading}\n" if heading else ""
    chunks: list[str] = []
    current = ""

    def push(block: str):
        nonlocal current
        if current.strip():
            chunks.append(current.strip())
            current = ""

    for para in paragraphs:
        if len(para) > chunk_size * 1.5:
            push(current)
            current = ""
            subs = _hard_split(para, chunk_size, overlap)
            # 给第一块加标题前缀
            if subs:
                subs[0] = prefix + subs[0]
            chunks.extend(s.strip() for s in subs if s.strip())
            continue
        # 段落并入当前块
        if current and len(current) + len(para) + 1 > chunk_size:
            chunks.append(current.strip())
            current = current[-overlap:] if overlap > 0 else ""
        current = (current + "\n" + para) if current else para

    if current.strip():
        chunks.append(current.strip())

    # 给每个块加标题前缀（若还没加且当前块未含标题）
    if prefix:
        for i in range(len(chunks)):
            if not chunks[i].startswith(heading):
                chunks[i] = prefix + chunks[i]

    return chunks