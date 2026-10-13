#!/usr/bin/env python3
import enrich
from inns_5000_loader import load_5000

INNS = load_5000()

def load_first_5000():
    enrich.log(f'Loaded first production batch: {len(INNS):,} INNs from plain-text parts')
    return INNS

enrich.load_inns = load_first_5000
enrich.main()
