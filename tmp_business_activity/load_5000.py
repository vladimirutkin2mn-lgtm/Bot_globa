from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent


def load():
    # Use only values that came from the source workbook. Some transfer chunks
    # overlap, so deduplicate while preserving first-seen order.
    raw = []
    for pattern in ('inns_5000_txt.part*', 'inns_5000_repair.part*'):
        for p in sorted(ROOT.glob(pattern)):
            raw.extend(x.strip() for x in p.read_text(encoding='utf-8').splitlines() if x.strip())

    inns = []
    seen = set()
    for x in raw:
        x = re.sub(r'\D', '', x)
        if 0 < len(x) < 10:
            x = x.zfill(10)
        if not re.fullmatch(r'\d{10}', x) or x in seen:
            continue
        seen.add(x)
        inns.append(x)

    assert len(inns) == 4748, f'Expected 4748 verified unique INNs, got {len(inns)}'
    return inns
