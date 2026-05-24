"""Gateway 用户 ID 校验（与 Core 规则一致，独立实现）。"""

import re

_SAFE_USER = re.compile(r"^[\w\-]{1,64}$")


def sanitize_user_id(user_id: str) -> str:
    uid = (user_id or "").strip()
    if not uid or not _SAFE_USER.match(uid):
        raise ValueError("用户 ID 仅允许字母、数字、下划线、横线，最长 64 字符")
    return uid
