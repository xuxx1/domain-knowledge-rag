"""文本清洗服务：在分块前过滤无意义内容

处理对象：
- AIGC 水印 YAML 块（ContentProducer/ContentPropagator/ProduceID/PropagateID/ReservedCode/Label 等）
- UUID（8-4-4-4-12 十六进制）
- HTML 残留标签/实体
- 乱码（异常 Unicode、重复字符、乱码替换符）
- 无意义页眉页脚（纯页码、版权行、导航文字等）
- 文档末尾的 AI 生成标注

在 chunker.chunk_text 之前调用，保证上传/补录/重建索引统一生效。
"""

import re

# ---------- 规则 ----------

# AIGC 水印 YAML 块：被 --- 包裹，含 AIGC/ContentProducer 等关键字的 front-matter
# AIGC 水印 YAML 块：被 --- 包裹，含 AIGC/ContentProducer 等关键字的 front-matter
_AIGC_YAML_BLOCK = re.compile(
    r"(?:^|\n)---\s*\n"
    r"(?P<body>[^-]*?)"
    r"(?P<kw>AIGC\s*:|ContentProducer:|ContentPropagator:|ProduceID:|PropagateID:|ReservedCode1:|ReservedCode2:)"
    r"[^-]*?\n---\s*(?=\n|$)",
    re.IGNORECASE,
)
# 单行含 AIGC 关键字
_AIGC_KEY_LINE = re.compile(
    r"^\s*(?:AIGC|ContentProducer|ContentPropagator|ContentId|ProduceID|PropagateID"
    r"|ReservedCode1|ReservedCode2|Label)\s*[:：].*$",
    re.IGNORECASE | re.MULTILINE,
)
# UUID 形式：8-4-4-4-12 十六进制
_UUID = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
# 长十六进制串（水印编码残留，如 '001191110102MAD55U9H0F10002' 类）
_LONG_CODE = re.compile(
    r"\b[0-9A-Z]{16,}\b",
)
# HTML 残留标签
_HTML_TAG = re.compile(r"<[^>]{0,80}?>")
_HTML_ENTITY = re.compile(r"&(?:nbsp|amp|quot|lt|gt|#\d+);")
# 乱码：替换符 U+FFFD 连续、重复的无意义字符
_GARBAGE_REPL = re.compile(r"\ufffd+")
# 纯分隔线（---、***、=== 等连续符号）
_DIVIDER = re.compile(r"^\s*(?:[-*=–_#·•]{3,}|。{3,}|…{3,})\s*$")
# 无意义页眉页脚：仅含"第X页/页码/页码 1 / Page 1"等
_PAGE_ONLY = re.compile(r"^\s*(?:第\s*\d+\s*页|Page\s*\d+|\d+\s*/?\s*\d+)\s*$", re.IGNORECASE)
# 文档末尾的 AI 生成标注
_AI_GEN = re.compile(r"^\s*[>＞]?\s*AI\s*生成\s*$", re.MULTILINE)
# 残留的 AIGC 头字段值（形如 001191110102MAD55U9H0F10002 的编码，通常在 AIGC 块内，已由块规则处理）
# 单行仅含空白/分隔符/无意义文字

# 无信息量短行（去空白后极短且不是有效句子）——交给后续 chunker 的空行归一处理

# 连续相同字符乱码（如 "!!!!!!" 或 "XXXXXXXXXXXXXXXX" 超长）
_REPEAT_GARBAGE = re.compile(r"(.)\1{15,}")


def _strip_front_matter(text: str) -> str:
    """移除 YAML front-matter（--- ... --- 或 --- ...）"""
    # 标准 front matter：文件开头 --- 包裹
    m = re.match(r"^\s*---\s*\n.*?\n---\s*(?=\n|$)", text, re.DOTALL)
    if m:
        text = text[m.end():]
    return text


def clean_text(text: str) -> str:
    """清洗入口：返回清洗后的文本"""
    if not text:
        return text

    # 1. 移除 AIGC YAML 块（含关键字的 front matter）
    text = _AIGC_YAML_BLOCK.sub("\n", text)
    # 2. 移除通用 YAML front-matter
    text = _safe_yaml_front_matter(text)
    # 3. 删除单行 AIGC 关键字
    text = _AIGC_KEY_LINE.sub("", text)
    # 4. 删除 UUID
    text = _UUID.sub("", text)
    # 5. 删除长编码（16+ 字母数字串）
    text = _LONG_CODE.sub("", text)
    # 6. HTML 残留
    text = _HTML_TAG.sub("", text)
    text = _HTML_ENTITY.sub(" ", text)
    # 7. 乱码
    text = _GARBAGE_REPL.sub(" ", text)
    text = _REPEAT_GARBAGE.sub(lambda m: m.group(1), text)
    # 8. 删除纯分隔符行、页码行、AI生成标注
    lines = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s:
            lines.append("")
            continue
        if _DIVIDER.match(s):
            continue
        if _PAGE_ONLY.match(s):
            continue
        if _AI_GEN.match(s):
            continue
        # 纯标点/符号行（无中英文、无数字）
        if re.fullmatch(r"[\s\W_]+", s):
            continue
        lines.append(ln)
    text = "\n".join(lines)

    # 归一空白：空行最多保留 1
    out: list[str] = []
    blank = 0
    for ln in text.splitlines():
        if ln.strip():
            out.append(ln)
            blank = 0
        else:
            blank += 1
            if blank <= 1:
                out.append("")
    return "\n".join(out).strip()


# 便捷别名（兼容命名）
clean = clean_text


def _safe_yaml_front_matter(text: str) -> str:
    """通用 YAML front-matter 移除（--- 开头到下一个 ---）"""
    m = re.match(r"^\s*---\s*\n(?:\s*[^-\n][^\n]*\n)*?---\s*(?=\n|$)", text)
    if m:
        return text[m.end():]
    return text