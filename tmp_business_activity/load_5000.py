from pathlib import Path
import base64, re, zlib

ROOT = Path(__file__).resolve().parent

def _partial_gzip_text():
    # The original full-INN archive in this temporary branch is truncated only
    # at the tail. Streaming zlib can still recover its intact prefix, which is
    # all we need for the first 5,000 source rows.
    parts = sorted(ROOT.glob('inns.b64.*'))
    if not parts:
        raise RuntimeError('No original INN archive parts found')
    b64 = ''.join(p.read_text(encoding='utf-8').strip() for p in parts)
    # A truncated base64 tail may not be aligned. Drop only the incomplete tail.
    b64 = b64[:len(b64) - (len(b64) % 4)]
    compressed = base64.b64decode(b64, validate=False)
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    raw = d.decompress(compressed)
    return raw.decode('utf-8', errors='ignore')

def load():
    raw = _partial_gzip_text()
    inns = []
    for line in raw.splitlines():
        x = re.sub(r'\D', '', line)
        if 0 < len(x) < 10:
            x = x.zfill(10)
        if re.fullmatch(r'\d{10}', x):
            inns.append(x)
        if len(inns) == 5000:
            break
    assert len(inns) == 5000, f'Only {len(inns)} INNs recovered from archive prefix'
    assert len(set(inns)) == 5000, (len(inns), len(set(inns)))
    return inns
