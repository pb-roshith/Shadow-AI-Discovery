from engine.config import reference

def decide(candidate):
    t = reference('scoring.yaml')['thresholds']
    checks = [
        ('R0', 'Exposed credential detected in a file or Git history',
         any(s['signal_type'] in ('credential_in_file', 'credential_in_history') for s in candidate['signals']), 'Raise issue'),
        ('R1', f'Confidence < {t["false_positive"]}', candidate['confidence'] < t['false_positive'], 'False positive'),
        ('R3', f'Not Approved and risk ≥ {t["issue_risk"]}', candidate['inventory']['status'] != 'Approved' and candidate['risk'] >= t['issue_risk'], 'Raise issue'),
        ('R4', f'Approved and risk ≥ {t["issue_risk"]}', candidate['inventory']['status'] == 'Approved' and candidate['risk'] >= t['issue_risk'], 'Raise issue'),
        ('R2', f'Approved and confidence ≥ {t["approved_confidence"]}', candidate['inventory']['status'] == 'Approved' and candidate['confidence'] >= t['approved_confidence'], 'Genuine'),
        ('R5', 'Otherwise', True, 'Monitor'),
    ]
    fired = next(rule for rule in checks if rule[2])
    candidate.update(decision=fired[3], rule=fired[0], decision_trace=[{'rule': rule, 'condition': condition, 'matched': matched, 'fired': rule == fired[0], 'decision': decision} for rule, condition, matched, decision in checks])
    candidate['decision_explanation'] = f'{fired[3]} under {fired[0]} ({fired[1]}). Confidence {candidate["confidence"]}/100; risk {candidate["risk"]}/100. ' + candidate['inventory']['reason']
    return candidate
