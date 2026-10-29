import hashlib

def detect(matches):
    """Stable per-run signal IDs; content is never part of the persisted schema."""
    result = []
    for index, match in enumerate(matches):
        signal = dict(match)
        signal['signal_id'] = 'SIG-' + hashlib.sha256(f'{signal["run_id"]}:{index}'.encode()).hexdigest()[:12]
        result.append(signal)
    return result
