"""The dispatcher must actually build, not merely mention its routers in source.

The telegram worker crash-looped in production for two days on
``RuntimeError: Router is already attached to <Router 'reading-feedback'>``: the story
routers were nested under the feedback router *and* registered on the dispatcher, and
aiogram allows a router exactly one parent. Every wiring test asserted against
``inspect.getsource(create_dispatcher)``, so the duplicate registration read as correct
and the suite stayed green while no Telegram update was processed at all.

``create_dispatcher`` mutates module-level router objects by assigning their parent, so a
second call inside the same interpreter fails on routers the first call already claimed.
These checks therefore run in a fresh interpreter, like the runtime model registry ones.
"""

import subprocess
import sys

_EXPECTED_ROUTERS = (
    "chat_scope",
    "reading-feedback",
    "reading-stories",
    "reading-story-continuation",
    "reading-story-link",
)

_BUILD_DISPATCHER = """
import os

os.environ.update(
    {
        "APP_ENV": "test",
        "DATABASE_URL": "postgresql+asyncpg://user:pass@db:5432/test",
        "TELEGRAM_BOT_TOKEN": "123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "CONTENT_ENCRYPTION_KEY": "test-only-key",
    }
)

from pydantic import SecretStr

from app.bot.main import create_dispatcher
from app.config import Settings

settings = Settings(
    app_env="test",
    database_url="postgresql+asyncpg://user:pass@db:5432/test",
    telegram_bot_token=SecretStr("123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"),
    content_encryption_key=SecretStr("test-only-key"),
)

dispatcher = create_dispatcher(settings)

names = []
pending = list(dispatcher.sub_routers)
while pending:
    router = pending.pop()
    names.append(router.name)
    pending.extend(router.sub_routers)

print("ROUTERS " + " ".join(sorted(names)))
"""


def _build_dispatcher_in_fresh_interpreter() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", _BUILD_DISPATCHER],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_create_dispatcher_builds_without_reattaching_a_router() -> None:
    completed = _build_dispatcher_in_fresh_interpreter()

    assert completed.returncode == 0, (
        "create_dispatcher raised while wiring routers, so the telegram worker cannot "
        f"start: {completed.stdout}{completed.stderr}"
    )


def test_every_reachable_router_is_registered_exactly_once() -> None:
    completed = _build_dispatcher_in_fresh_interpreter()
    assert completed.returncode == 0, f"{completed.stdout}{completed.stderr}"

    line = next(line for line in completed.stdout.splitlines() if line.startswith("ROUTERS "))
    names = line.removeprefix("ROUTERS ").split()

    duplicates = sorted({name for name in names if names.count(name) > 1})
    assert not duplicates, f"routers registered more than once: {duplicates}"

    missing = [name for name in _EXPECTED_ROUTERS if name not in names]
    assert not missing, f"routers unreachable from the dispatcher: {missing}"
