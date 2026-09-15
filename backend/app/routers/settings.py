"""参数设置路由：读取/更新 RAG 可调参数

- GET  /api/settings          读取当前所有可调参数及说明
- PUT  /api/settings          更新参数（写回 .env 持久化 + 动态改内存立即生效）

说明：
- 检索类参数（阈值、K 值、判定阈值等）更新后立即生效，无需重启。
- 分块类参数（CHUNK_SIZE / CHUNK_OVERLAP）影响已入库文档的切分，需对文档重建索引才应用到存量数据；
  新上传文档直接用新值。
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import config

router = APIRouter(prefix="/settings", tags=["参数设置"])

# 每个可调参数：默认值、类型、最小值、最大值、说明
# 供前端渲染表单与校验；写 .env 时按类型序列化
SETTINGS_META: dict[str, dict] = {
    "CHUNK_SIZE": {
        "key": "CHUNK_SIZE", "type": "int", "default": 700,
        "min": 100, "max": 2000, "label": "分块目标字符数",
        "desc": "文档按此字符数切块（建议500-800）。越大每块信息越完整、检索定位越粗；越小越精细、上下文越碎。新上传文档生效，存量需重建索引。",
    },
    "CHUNK_OVERLAP": {
        "key": "CHUNK_OVERLAP", "type": "int", "default": 120,
        "min": 0, "max": 500, "label": "分块重叠字符数",
        "desc": "相邻块之间的重叠（建议100-150），避免关键信息恰好被切断在块边界。应小于分块目标字符数。新上传文档生效。",
    },
    "RETRIEVAL_TOP_K": {
        "key": "RETRIEVAL_TOP_K", "type": "int", "default": 8,
        "min": 1, "max": 50, "label": "向量召回数量",
        "desc": "从向量库取前 N 个候选片段进入后续处理。越大召回越全但噪声越多、越慢。立即生效。",
    },
    "RERANK_TOP_K": {
        "key": "RERANK_TOP_K", "type": "int", "default": 4,
        "min": 1, "max": 20, "label": "生成上下文片段数",
        "desc": "最终进入 LLM 生成上下文的片段数。越大上下文越足但越耗 token。立即生效。",
    },
    "RANK_DOC_LIMIT": {
        "key": "RANK_DOC_LIMIT", "type": "int", "default": 4,
        "min": 1, "max": 20, "label": "同文档最多保留片段数",
        "desc": "同一文档最多保留多少候选片段。单文档论文入库建议调高（如 4-6）以免答案片段被挤掉；多文档库可调低（1-2）避免刷屏。立即生效。",
    },
    "SCORE_THRESHOLD": {
        "key": "SCORE_THRESHOLD", "type": "float", "default": 0.35,
        "min": 0.0, "max": 1.0, "label": "相似度过滤阈值",
        "desc": "检索片段相似度低于此值直接丢弃。越低越容易命中、越易误检；越高越严格、越易漏检。立即生效。",
    },
    "ANSWERABLE_MIN_SCORE": {
        "key": "ANSWERABLE_MIN_SCORE", "type": "float", "default": 0.50,
        "min": 0.0, "max": 1.0, "label": "可回答性兜底阈值",
        "desc": "命中片段最高相似度低于此值即判不可回答（进盲区）。调低(如0.40)更易给答案但准确性下降；调高更保守拒答。立即生效。",
    },
    "EN_KB_CJK_RATIO": {
        "key": "EN_KB_CJK_RATIO", "type": "float", "default": 0.10,
        "min": 0.0, "max": 1.0, "label": "英文库判定阈值",
        "desc": "文档分块中中文字符占比低于此值视为英文文档库，此时中文提问自动翻译成英文再检索（中文文档不受影响）。立即生效。",
    },
}

_ENV_FILE = config.BASE_DIR / ".env"


def _get_value(key: str, meta: dict) -> float | int:
    """读取当前生效值：优先内存 config，回退默认"""
    val = getattr(config, key, None)
    if val is not None:
        return val
    default = meta["default"]
    return float(default) if meta["type"] == "float" else int(default)


def _coerce(key: str, meta: dict, raw) -> float | int:
    """类型转换 + 范围校验"""
    try:
        v = float(raw) if meta["type"] == "float" else int(raw)
    except (TypeError, ValueError):
        raise HTTPException(422, f"参数 {key} 必须是{'数字' if meta['type'] == 'float' else '整数'}")
    if v < meta["min"] or v > meta["max"]:
        raise HTTPException(422, f"参数 {key} 超出范围 [{meta['min']}, {meta['max']}]")
    return v


def _write_env(updates: dict[str, str]):
    """把新值写回 .env，保留原注释与顺序；无该键则追加到文件末尾。"""
    lines: list[str] = []
    if _ENV_FILE.exists():
        lines = _ENV_FILE.read_text(encoding="utf-8").splitlines()

    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k = stripped.split("=", 1)[0].strip()
            if k in updates:
                new_lines.append(f"{k}={updates[k]}")
                continue
        new_lines.append(line)

    # 追加不存在的键
    written = {
        l.split("=", 1)[0].strip()
        for l in new_lines
        if "=" in l and not l.strip().startswith("#")
    }
    for k, v in updates.items():
        if k not in written:
            new_lines.append(f"{k}={v}")

    _ENV_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


class SettingsUpdate(BaseModel):
    """可部分更新的参数字典"""
    values: dict[str, float | int] = Field(default_factory=dict)


@router.get("")
def get_settings():
    """返回全部可调参数：当前值 + 元信息（类型/范围/说明）"""
    items = []
    for meta in SETTINGS_META.values():
        key = meta["key"]
        items.append(
            {
                "key": key,
                "label": meta["label"],
                "desc": meta["desc"],
                "type": meta["type"],
                "min": meta["min"],
                "max": meta["max"],
                "default": meta["default"],
                "value": _get_value(key, meta),
            }
        )
    return {"items": items}


@router.put("")
def update_settings(body: SettingsUpdate):
    """更新参数：校验 → 写 .env 持久化 → 改内存立即生效"""
    if not body.values:
        raise HTTPException(400, "没有需要更新的参数")

    updates: dict[str, str] = {}
    for key, raw in body.values.items():
        meta = SETTINGS_META.get(key)
        if not meta:
            raise HTTPException(404, f"未知参数 {key}")
        v = _coerce(key, meta, raw)
        updates[key] = str(v)
        # 动态改内存，立即生效（无需重启）
        setattr(config, key, v)

    try:
        _write_env(updates)
    except Exception as e:  # noqa: BLE001
        # 写 .env 失败不回滚已改的内存值（运行时已生效），但需提示用户
        raise HTTPException(
            500, f"写回 .env 失败（参数已在内存生效，重启后可能丢失）：{e}"
        )

    return {"ok": True, "updated": {k: updates[k] for k in updates}}