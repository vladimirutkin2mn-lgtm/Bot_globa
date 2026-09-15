#!/usr/bin/env python3
import base64, gzip, re
from pathlib import Path
import enrich

ROOT = Path(__file__).resolve().parent
raw = gzip.decompress(base64.b64decode((ROOT / 'inns_1000.b64').read_text().strip())).decode('utf-8')
INNS = [x.strip() for x in raw.splitlines() if re.fullmatch(r'\d{10}', x.strip())]
assert len(INNS) == 1000, len(INNS)
assert len(set(INNS)) == 1000

def load_first_1000():
    enrich.log(f'Loaded first batch: {len(INNS):,} INNs')
    return INNS

enrich.load_inns = load_first_1000
enrich.main()
