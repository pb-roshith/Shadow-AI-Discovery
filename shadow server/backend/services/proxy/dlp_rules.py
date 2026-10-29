"""Pure detection: return aggregate labels, never the values that matched."""
import re


def scan(data: bytes, patterns: list[dict]) -> list[dict]:
    text = data.decode('utf-8', errors='ignore')
    counts = {}
    for pattern in patterns:
        count = sum(1 for _ in re.finditer(pattern['regex'], text))
        if count:
            label = pattern['label']
            counts[label] = counts.get(label, 0) + count
    return [{'label': label, 'match_count': count} for label, count in counts.items()]
