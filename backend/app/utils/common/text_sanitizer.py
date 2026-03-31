import html
import re

def sanitize_story(raw: str) -> str:
    if not raw:
        return ""

    text = html.unescape(raw)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[\u00a0\u202f\u2009\u2007\u2002\u2003]", " ", text)
    text = re.sub(r"[^\S\n\t ]+", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()