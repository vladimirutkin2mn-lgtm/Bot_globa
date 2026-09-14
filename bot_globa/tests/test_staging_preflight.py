import os
import subprocess
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "preflight_staging_remote.sh"
_PUBLIC_ENV = Path(__file__).resolve().parents[1] / "staging.public.env"


def _valid_env() -> str:
    return """\
APP_ENV=staging
POSTGRES_DB=bot_globa_staging
POSTGRES_PASSWORD=staging-db-secret
DATABASE_URL=postgresql+asyncpg://bot_globa_staging:staging-db-secret@db:5432/bot_globa_staging
TELEGRAM_BOT_TOKEN=123456:test-bot-token
TELEGRAM_WEBHOOK_URL=https://staging.example.test/telegram/webhook
TELEGRAM_WEBHOOK_SECRET=telegram-webhook-secret
CONTENT_ENCRYPTION_KEY=staging-content-key
LLM_PROVIDER=openai
OPENAI_API_KEY=staging-openai-key
LLM_MODEL=gpt-test
PAYMENT_PROVIDER=yookassa
PAYMENT_PUBLIC_BASE_URL=https://staging.example.test
PAYMENT_WEBHOOK_SECRET=payment-webhook-secret
YOOKASSA_SHOP_ID=test-shop-id
YOOKASSA_SECRET_KEY=test-yookassa-secret
STRIPE_SECRET_KEY=sk_test_staging
STRIPE_WEBHOOK_SECRET=whsec_staging
ADMIN_API_TOKEN=staging-admin-token
"""


def _run_preflight(tmp_path: Path, content: str) -> subprocess.CompletedProcess[str]:
    env_file = tmp_path / ".env.staging"
    env_file.write_text(content, encoding="utf-8")
    env = os.environ.copy()
    env["STAGING_ENV_FILE"] = str(env_file)
    env["STAGING_PUBLIC_ENV_FILE"] = str(_PUBLIC_ENV)
    return subprocess.run(
        ["bash", str(_SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_staging_preflight_accepts_isolated_sandbox_config(tmp_path: Path) -> None:
    result = _run_preflight(tmp_path, _valid_env())

    assert result.returncode == 0, result.stderr
    assert "Staging preflight passed" in result.stdout


def test_staging_preflight_rejects_placeholder_public_url(tmp_path: Path) -> None:
    content = _valid_env().replace(
        "PAYMENT_PUBLIC_BASE_URL=https://staging.example.test",
        "PAYMENT_PUBLIC_BASE_URL=https://staging.example.invalid",
    )

    result = _run_preflight(tmp_path, content)

    assert result.returncode != 0
    assert "PAYMENT_PUBLIC_BASE_URL" in result.stderr


def test_staging_preflight_rejects_embedded_database_placeholder(tmp_path: Path) -> None:
    content = _valid_env().replace(
        "staging-db-secret@db:5432/bot_globa_staging",
        "CHANGE_ME@db:5432/bot_globa_staging",
    )

    result = _run_preflight(tmp_path, content)

    assert result.returncode != 0
    assert "DATABASE_URL" in result.stderr
    assert "CHANGE_ME" not in result.stdout + result.stderr


def test_staging_preflight_rejects_production_database(tmp_path: Path) -> None:
    content = _valid_env().replace(
        "POSTGRES_DB=bot_globa_staging",
        "POSTGRES_DB=bot_globa",
    )

    result = _run_preflight(tmp_path, content)

    assert result.returncode != 0
    assert "POSTGRES_DB" in result.stderr


def test_staging_preflight_rejects_live_stripe_without_leaking_key(tmp_path: Path) -> None:
    live_key = "sk_live_must_never_appear_in_logs"
    content = _valid_env().replace("sk_test_staging", live_key)

    result = _run_preflight(tmp_path, content)
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert "STRIPE_SECRET_KEY" in result.stderr
    assert live_key not in output
