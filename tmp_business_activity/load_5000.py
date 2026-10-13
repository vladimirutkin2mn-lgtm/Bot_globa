import base64, gzip, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def load():
    parts = sorted(ROOT.glob('inns_5000.b64.*'))
    assert len(parts) == 3, [p.name for p in parts]
    payload = ''.join(p.read_text(encoding='utf-8').strip() for p in parts)
    raw = gzip.decompress(base64.b64decode(payload)).decode('utf-8')
    inns = [x.strip() for x in raw.splitlines() if re.fullmatch(r'\d{10}', x.strip())]
    assert len(inns) == 5000, len(inns)
    assert len(set(inns)) == 5000
    return inns
