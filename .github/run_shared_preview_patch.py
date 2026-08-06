"""Execute the temporary shared-preview patch embedded in its workflow."""

from pathlib import Path
import re

SOURCE = Path(".github/workflows/apply-shared-free-preview.yml")
START = "          python - <<'PY'\n"
END = "\n          PY\n"

source = SOURCE.read_text()
if START not in source or END not in source:
    raise SystemExit("embedded patch markers are missing")
embedded = source.split(START, 1)[1].split(END, 1)[0]
body = "\n".join(
    line[10:] if line.startswith("          ") else line
    for line in embedded.splitlines()
)
exact = '''def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text()
    if text.count(old) != 1:
        raise SystemExit(f'expected one anchor in {path}: {old[:80]!r}')
    target.write_text(text.replace(old, new, 1))'''
robust = '''def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text()
    if text.count(old) == 1:
        target.write_text(text.replace(old, new, 1))
        return
    pattern = re.compile(r"\\s+".join(re.escape(token) for token in old.split()))
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise SystemExit(f"expected one structural anchor in {path}, got {len(matches)}")
    match = matches[0]
    target.write_text(text[: match.start()] + new + text[match.end() :])'''
if exact not in body:
    raise SystemExit("replace_once definition is missing")
body = body.replace(exact, robust, 1)
exec(compile(body, "<shared-preview-patch>", "exec"))
