"""LLM 服务：OpenAI 兼容 API 封装（流式 + 非流式）"""

import time

from .. import config


class LLMError(Exception):
    pass


def _client():
    if not config.LLM_API_KEY or config.LLM_API_KEY.startswith("sk-xxx"):
        raise LLMError("LLM_API_KEY 未配置，请编辑 backend/.env")
    from openai import OpenAI

    return OpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY)


def chat(messages: list[dict], **kwargs) -> str:
    """非流式：返回完整文本"""
    client = _client()
    try:
        resp = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=messages,
            temperature=kwargs.get("temperature", config.LLM_TEMPERATURE),
            max_tokens=kwargs.get("max_tokens", config.LLM_MAX_TOKENS),
        )
        return resp.choices[0].message.content or ""
    except LLMError:
        raise
    except Exception as e:  # noqa: BLE001
        raise LLMError(f"LLM 调用失败：{e}") from e


def chat_stream(messages: list[dict], **kwargs):
    """流式：yield 文本增量片段"""
    client = _client()
    try:
        stream = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=messages,
            temperature=kwargs.get("temperature", config.LLM_TEMPERATURE),
            max_tokens=kwargs.get("max_tokens", config.LLM_MAX_TOKENS),
            stream=True,
        )
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    except LLMError:
        raise
    except Exception as e:  # noqa: BLE001
        raise LLMError(f"LLM 流式调用失败：{e}") from e


def translate_to_en(text: str) -> str:
    """把用户问题翻译成英文，供对英文文档检索使用。失败时返回原文本（降级为不翻译）。"""
    try:
        out = chat(
            [
                {"role": "system", "content": "你是翻译助手。把用户的中文问题翻译为准确、简洁的英文，直接输出英文译文，不要加解释或标点。"},
                {"role": "user", "content": text[:500]},
            ],
            max_tokens=128,
            temperature=0.0,
        )
        translated = (out or "").strip().strip('"“”')
        return translated if translated else text
    except Exception:  # noqa: BLE001
        return text


def generate_title(question: str) -> str:
    """根据首问生成会话标题（截断降级）"""
    try:
        text = chat(
            [
                {"role": "system", "content": "用不超过12个字概括用户问题，直接输出标题，不要标点。"},
                {"role": "user", "content": question[:500]},
            ],
            max_tokens=30,
            temperature=0.1,
        )
        return text.strip().strip('"“”')[:20] or question[:20]
    except Exception:  # noqa: BLE001
        return question[:20]


def timed(fn, *args, **kwargs):
    """计时工具（供分析模块统计首字延迟等）"""
    start = time.time()
    result = fn(*args, **kwargs)
    return result, time.time() - start
