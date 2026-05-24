"""从 LLM 整段回复中分离口语与 form_update JSON。"""

import json
import re

from vtuber.utils.sentence_buffer import truncate_before_json

_FORM_UPDATE_LINE = re.compile(r"^```(?:json)?\s*$", re.IGNORECASE)
_FORM_UPDATE_FENCED = re.compile(
    r"```(?:json)?\s*\n(\{.*?\})\s*```",
    re.DOTALL | re.IGNORECASE,
)


def parse_form_update_object(raw: str) -> dict | None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or "form_update" not in data:
        return None
    fu = data.get("form_update")
    return fu if isinstance(fu, dict) else None


def parse_reply_with_form(full_text: str) -> tuple[str, dict | None]:
    """口语 + 末尾 form_update；剥离 ```json 围栏，口语侧走 truncate_before_json。"""
    text = full_text.strip()
    form_update: dict | None = None

    fenced = _FORM_UPDATE_FENCED.search(text)
    if fenced:
        form_update = parse_form_update_object(fenced.group(1))
        return truncate_before_json(text[: fenced.start()]).strip(), form_update

    reply_lines: list[str] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if _FORM_UPDATE_LINE.match(s):
            if i + 1 < len(lines):
                nxt = lines[i + 1].strip()
                if nxt.startswith("{") and nxt.endswith("}"):
                    if parse_form_update_object(nxt) is not None or '"form_update"' in nxt:
                        form_update = parse_form_update_object(nxt)
                        i += 2
                        if i < len(lines) and lines[i].strip() == "```":
                            i += 1
                        continue
            i += 1
            continue
        if s.startswith("{") and s.endswith("}"):
            if parse_form_update_object(s) is not None or '"form_update"' in s:
                form_update = parse_form_update_object(s)
                i += 1
                continue
        reply_lines.append(lines[i])
        i += 1

    reply = truncate_before_json("\n".join(reply_lines).strip())
    return reply or truncate_before_json(text), form_update
