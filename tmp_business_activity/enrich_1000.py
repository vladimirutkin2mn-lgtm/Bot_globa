#!/usr/bin/env python3
import re
from pathlib import Path
import enrich

ROOT = Path(__file__).resolve().parent
parts = [ROOT / f'inns_1000.part{i}' for i in range(1, 5)]
raw = ''.join(p.read_text(encoding='utf-8') for p in parts)
INNS = [x.strip() for x in raw.splitlines() if re.fullmatch(r'\d{10}', x.strip())]
assert len(INNS) == 1000, len(INNS)
assert len(set(INNS)) == 1000

def load_first_1000():
    enrich.log(f'Loaded first batch: {len(INNS):,} INNs')
    return INNS

enrich.load_inns = load_first_1000
enrich.main()
