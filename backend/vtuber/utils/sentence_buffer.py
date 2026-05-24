"""LLM 流式输出时增量切句；TTS 仅使用口语部分，排除 form_update JSON。"""

import re

_SENTENCE_END = re.compile(r"(?<=[。！？；.!?…\n~～])")
# 无句末标点时：仅在过长时按空格弱切或硬切（不在逗号处切，避免句间停顿过长）
_MAX_TTS_CHARS = 180
_WEAK_SPLIT_AT = 120  # 流式过程中无句末标点，达到该长度即尝试弱分隔
# 弱分隔：半角/全角空格、制表（不含逗号）
_WEAK_SEPS = ("\u3000", " ", "\t")
# 口语与 JSON 分界（同行或换行后的 {）
_JSON_START = re.compile(
    r'(\n\s*\{|\{\s*"form_update"|\{\s*\'form_update\')',
    re.IGNORECASE,
)
_MARKDOWN_FENCE_LINE = re.compile(r"^```(?:json)?\s*$", re.IGNORECASE)


def truncate_before_json(text: str) -> str:
    """截断 JSON / markdown 围栏起点之前的内容，供 TTS 与展示使用。"""
    if not text:
        return ""
    lower = text.lower()
    for needle in ("```json", "```"):
        i = lower.find(needle)
        if i != -1:
            text = text[:i]
            lower = text.lower()
    m = _JSON_START.search(text)
    if m:
        text = text[: m.start()]
    lines = text.split("\n")
    while lines:
        tail = lines[-1].strip()
        if tail.startswith("{") or _MARKDOWN_FENCE_LINE.match(tail):
            lines.pop()
        else:
            break
    return "\n".join(lines).rstrip()


def is_tts_safe_sentence(s: str) -> bool:
    """过滤误送入 TTS 的 JSON / 表单字段片段。"""
    s = s.strip()
    if not s or s.startswith("{") or _MARKDOWN_FENCE_LINE.match(s):
        return False
    if s.lower() in ("json", "`", "``", "```"):
        return False
    if "form_update" in s:
        return False
    if re.search(
        r'"(user_profile|current_topic|historical_interests|historical_interest_updates)"\s*:',
        s,
    ):
        return False
    if re.search(r"[\{\}\[\]]", s) and (
        "user_profile" in s
        or "historical_interests" in s
        or "historical_interest_updates" in s
    ):
        return False
    return True


def _split_at_weak_sep(text: str, max_chars: int) -> tuple[list[str], str]:
    """在 max_chars 范围内，从后往前找弱分隔（含空格）切一刀。"""
    text = text.strip()
    if len(text) <= max_chars:
        return [], text
    min_head = 4
    for sep in _WEAK_SEPS:
        pos = text.rfind(sep, 0, max_chars + 1)
        if pos < min_head:
            continue
        # 空格类分隔：切在分隔符后，不保留尾部空格进 head
        if sep in ("\u3000", " ", "\t"):
            head = text[:pos].strip()
            tail = text[pos + len(sep) :].strip()
        else:
            head = text[: pos + len(sep)].strip()
            tail = text[pos + len(sep) :].strip()
        if head and is_tts_safe_sentence(head):
            return [head], tail
    head = text[:max_chars].strip()
    tail = text[max_chars:].strip()
    if head and is_tts_safe_sentence(head):
        return [head], tail
    return [], text


def _split_oversized_chunk(text: str, max_chars: int = _MAX_TTS_CHARS) -> tuple[list[str], str]:
    return _split_at_weak_sep(text, max_chars)


def _chunks_for_tts(text: str) -> list[str]:
    text = truncate_before_json(text).strip()
    if not text:
        return []
    result: list[str] = []
    parts = _SENTENCE_END.split(text)
    if len(parts) > 1:
        segments = [p.strip() for p in parts[:-1] if p.strip()]
        if parts[-1].strip():
            segments.append(parts[-1].strip())
    else:
        segments = [text]
    for seg in segments:
        while seg:
            seg = seg.strip()
            if not seg:
                break
            if len(seg) <= _MAX_TTS_CHARS:
                if is_tts_safe_sentence(seg):
                    result.append(seg)
                break
            forced, seg = _split_oversized_chunk(seg)
            result.extend(forced)
    # 末句无句末标点：整段仍应进 TTS（含短尾句）
    if not result and is_tts_safe_sentence(text):
        result.append(text)
    return result


def drain_complete_sentences(buffer: str) -> tuple[list[str], str]:
    buffer = truncate_before_json(buffer)
    if not buffer:
        return [], ""

    sentences: list[str] = []
    parts = _SENTENCE_END.split(buffer)
    if len(parts) <= 1:
        if len(buffer) > _MAX_TTS_CHARS:
            forced, remainder = _split_oversized_chunk(buffer)
            return forced, truncate_before_json(remainder)
        if len(buffer) >= _WEAK_SPLIT_AT:
            forced, remainder = _split_at_weak_sep(buffer, _WEAK_SPLIT_AT)
            if forced:
                return forced, truncate_before_json(remainder)
        return [], buffer

    for part in parts[:-1]:
        for s in _chunks_for_tts(part):
            sentences.append(s)

    remainder = truncate_before_json(parts[-1])
    return sentences, remainder


def flush_remaining(buffer: str) -> list[str]:
    return _chunks_for_tts(buffer)
