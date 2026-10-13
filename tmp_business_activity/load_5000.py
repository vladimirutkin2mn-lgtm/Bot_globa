from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent

def load():
    inns = []
    for pattern in ('inns_5000_txt.part*', 'inns_5000_repair.part*'):
        for p in sorted(ROOT.glob(pattern)):
            inns.extend(x.strip() for x in p.read_text(encoding='utf-8').splitlines() if x.strip())
    assert len(inns) == 5000, len(inns)
    assert len(set(inns)) == 5000, (len(inns), len(set(inns)))
    assert all(re.fullmatch(r'\d{10}', x) for x in inns)
    return inns
