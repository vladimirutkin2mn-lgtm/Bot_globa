from pathlib import Path

ROOT = Path(__file__).resolve().parent

def load_5000():
    inns = []
    for pattern in ('inns_5000_txt.part*', 'inns_5000_repair.part*'):
        for p in sorted(ROOT.glob(pattern)):
            inns.extend(x.strip() for x in p.read_text(encoding='utf-8').splitlines() if x.strip())
    if len(inns) != 5000:
        raise RuntimeError(f'Expected 5000 INNs, got {len(inns)}')
    if len(set(inns)) != 5000:
        raise RuntimeError(f'INNs are not unique: rows={len(inns)}, unique={len(set(inns))}')
    bad = [x for x in inns if len(x) != 10 or not x.isdigit()]
    if bad:
        raise RuntimeError(f'Bad INNs: {bad[:10]}')
    return inns
