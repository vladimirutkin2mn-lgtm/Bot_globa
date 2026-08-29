"""Every runtime entrypoint must resolve the whole mapped schema, not part of it.

SQLAlchemy resolves a foreign key to its target table on the first flush that sorts
mapped tables, so an entrypoint that never imports a referenced model starts cleanly and
then fails while writing. The billing worker shipped in exactly that state: inserting
``credit_transactions`` raised ``NoReferencedTableError`` for ``readings``, and a captured
YooKassa payment retried itself into ``manual_review`` without ever granting credits.

These checks must run in a fresh interpreter. Inside pytest the registry is already
complete because some other module imported the missing models, which is precisely why
the defect survived a green suite.
"""

import subprocess
import sys

import pytest

RUNTIME_ENTRYPOINTS = (
    "app.api.main",
    "app.bot.main",
    "app.workers.billing",
    "app.workers.telegram",
    "app.workers.maintenance",
    "app.workers.oracle_memory",
    "app.workers.daily_horoscope",
)

_RESOLVE_EVERY_FOREIGN_KEY = """
import importlib, sys
importlib.import_module({entrypoint!r})
from app.db.base import Base

unresolved = []
for table in Base.metadata.tables.values():
    for key in table.foreign_keys:
        try:
            key.column
        except Exception as error:
            unresolved.append(f"{{table.name}}.{{key.parent.name}} -> {{key._colspec}}: {{error}}")
if unresolved:
    sys.stdout.write("UNRESOLVED " + " | ".join(sorted(unresolved)))
    raise SystemExit(1)
sys.stdout.write(f"OK {{len(Base.metadata.tables)}}")
"""


def _run_in_fresh_interpreter(entrypoint: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", _RESOLVE_EVERY_FOREIGN_KEY.format(entrypoint=entrypoint)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


@pytest.mark.parametrize("entrypoint", RUNTIME_ENTRYPOINTS)
def test_entrypoint_resolves_every_mapped_foreign_key(entrypoint: str) -> None:
    completed = _run_in_fresh_interpreter(entrypoint)
    assert completed.returncode == 0, (
        f"{entrypoint} cannot resolve its mapped schema and would fail on flush, "
        f"not on start: {completed.stdout}{completed.stderr}"
    )
    assert completed.stdout.startswith("OK ")


def test_the_billing_worker_can_build_a_credit_transaction_insert() -> None:
    """Reproduce the money-losing flush directly: the ledger insert must compile."""
    script = (
        "import app.workers.billing\n"
        "from sqlalchemy.dialects import postgresql\n"
        "from app.db.models import CreditTransaction\n"
        "statement = CreditTransaction.__table__.insert()\n"
        "print(statement.compile(dialect=postgresql.dialect()))\n"
        "from sqlalchemy.orm import class_mapper\n"
        "assert class_mapper(CreditTransaction)._sorted_tables\n"
        "print('OK')\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, (
        "the billing worker cannot insert a credit transaction: "
        f"{completed.stdout}{completed.stderr}"
    )
    assert completed.stdout.rstrip().endswith("OK")
