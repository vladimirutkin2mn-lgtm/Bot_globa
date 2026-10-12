#!/usr/bin/env python3
import enrich

_full = enrich.load_inns()
INNS = _full[:5000]
assert len(INNS) == 5000
assert len(set(INNS)) == 5000

def load_first_5000():
    enrich.log(f'Loaded first production batch: {len(INNS):,} INNs')
    return INNS

enrich.load_inns = load_first_5000
enrich.main()
