"""Reject conversational loops before a response reaches the user."""
import re
from difflib import SequenceMatcher


def normalized(text: str) -> str:
    return re.sub(r'[\W_]+', '', text.casefold())


def repeats(text: str, previous: list[str]) -> bool:
    value = normalized(text)
    if not value:
        return False
    sentences = [normalized(s) for s in re.split(r'[。！？.!?\n]', text) if len(normalized(s)) >= 10]
    if len(sentences) != len(set(sentences)):
        return True
    for old in previous:
        other = normalized(old)
        if not other:
            continue
        if value == other or SequenceMatcher(None, value, other).ratio() >= .84:
            return True
        if len(value) >= 6 and value in other:
            return True
        old_sentences = {normalized(s) for s in re.split(r'[。！？.!?\n]', old)}
        if sentences and all(s in old_sentences for s in sentences):
            return True
    return False
