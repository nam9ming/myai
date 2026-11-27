"""시민 공지의 수집 자료 준비."""

import re
from urllib.parse import urlsplit


def official_url(value: str) -> str | None:
    if not value or re.search(r"[\s\\\x00-\x1f\x7f]", value):
        return None
    try:
        parts = urlsplit(value)
        if (parts.scheme in {"http", "https"} and parts.hostname
                and parts.username is None and parts.password is None and parts.port != 0):
            return value
    except ValueError:
        pass
    return None
