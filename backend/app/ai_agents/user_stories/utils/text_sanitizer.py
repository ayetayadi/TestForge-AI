import html
import re
from typing import Union, List


def sanitize_story(raw: Union[str, List]) -> str:
    """Nettoie une story brute"""
    if isinstance(raw, list):
        raw = " ".join(str(x) for x in raw)
    
    if not raw:
        return ""
    
    text = html.unescape(str(raw))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[\u00a0\u202f\u2009\u2007\u2002\u2003]", " ", text)
    text = re.sub(r"[^\S\n\t ]+", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    
    return text.strip()


def normalize_text(s: Union[str, List]) -> str:
    """Normalise un texte pour comparaison"""
    if isinstance(s, list):
        s = " ".join(str(x) for x in s)
    if not isinstance(s, str):
        s = str(s or "")
    return re.sub(r"\s+", " ", s.strip().lower())


def truncate_text(text: str, max_length: int = 100) -> str:
    """Tronque un texte pour l'affichage"""
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."