"""Deployment policy, managed database URL, and release-command tests."""

import subprocess
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from app.cli.release import asyncpg_dsn
from app.config import Settings
from app.db.session import normalize_async_database_url
from app.deployment import (
    DeploymentSettings,
    validate_telegram_webhook,
    validate_telegram_worker,
)


def test_managed_postgres_urls_select_asyncpg() -> None:
    assert normalize_async_database_url("postgres://u:p@db/name") == (
        "postgresql+asyncpg://u:p@db/name"
    )
    assert normalize_async_database_url("postgresql://u:p@db/name") == (
        "postgresql+asyncpg://u:p@db/name"
    )
    assert normalize_async_database_url("postgresql+asyncpg://u:p@db/name") == (
        "postgresql+asyncpg://u:p@db/name"
    )
    assert asyncpg_dsn("postgres://u:p@db/name") == "postgresql://u:p@db/name"
    assert asyncpg_dsn("postgresql+asyncpg://u:p@db/name") == "postgresql://u:p@db/name"
    assert asyncpg_dsn("postgresql://u:p@db/name") == "postgresql://u:p@db/name"


def test_webhook_policy_accepts_local_and_strong_production_urls(settings: Settings) -> None:
    local = settings.model_copy(
        update={
            "telegram_webhook_url": "http://localhost:8000/telegram/webhook",
            "telegram_webhook_secret": SecretStr("local-secret"),
        }
    )
    validate_telegram_webhook(local)

    production = settings.model_copy(
        update={
            "app_env": "production",
            "telegram_webhook_url": "https://example.com/telegram/webhook",
            "telegram_webhook_secret": SecretStr("a" * 32),
        }
    )
    validate_telegram_webhook(production)


@pytest.mark.parametrize(
    ("url", "secret"),
    [
        ("https://example.com/wrong", "a" * 32),
        ("https://example.com/telegram/webhook?token=x", "a" * 32),
        ("http://example.com/telegram/webhook", "a" * 32),
        ("https://example.com/telegram/webhook", "short"),
        ("https://example.com/telegram/webhook", "unsafe secret value"),
    ],
)
def test_production_webhook_policy_fails_closed(settings: Settings, url: str, secret: str) -> None:
    configured = settings.model_copy(
        update={
            "app_env": "production",
            "telegram_webhook_url": url,
            "telegram_webhook_secret": SecretStr(secret),
        }
    )
    with pytest.raises(ValueError):
        validate_telegram_webhook(configured)


def test_telegram_worker_lease_covers_configured_llm_budget(settings: Settings) -> None:
    webhook_settings = settings.model_copy(
        update={
            "telegram_webhook_url": "https://example.com/telegram/webhook",
            "telegram_webhook_secret": SecretStr("a" * 32),
        }
    )
    validate_telegram_worker(
        webhook_settings,
        DeploymentSettings(telegram_update_lease_seconds=300),
    )
    with pytest.raises(ValueError, match="shorter than"):
        validate_telegram_worker(
            webhook_settings,
            DeploymentSettings(telegram_update_lease_seconds=120),
        )


def test_telegram_worker_requires_webhook_mode(settings: Settings) -> None:
    with pytest.raises(ValueError, match="requires webhook mode"):
        validate_telegram_worker(settings, DeploymentSettings())


def test_deployment_settings_reject_unbounded_values() -> None:
    with pytest.raises(ValidationError):
        DeploymentSettings(telegram_webhook_max_bytes=0)
    with pytest.raises(ValidationError):
        DeploymentSettings(telegram_update_lease_seconds=29)
    with pytest.raises(ValidationError):
        DeploymentSettings(telegram_update_retry_base_seconds=0)
    with pytest.raises(ValidationError):
        DeploymentSettings(telegram_update_max_attempts=101)
    with pytest.raises(ValidationError):
        DeploymentSettings(telegram_worker_idle_seconds=0)
    with pytest.raises(ValidationError):
        DeploymentSettings(daily_horoscope_lease_seconds=29)
    with pytest.raises(ValidationError):
        DeploymentSettings(daily_horoscope_worker_idle_seconds=0)
    with pytest.raises(ValidationError):
        DeploymentSettings(maintenance_batch_size=10_001)


def test_production_compose_loads_the_approved_stars_rollout_after_secrets() -> None:
    root = Path(__file__).parents[1]
    values = dict(
        line.split("=", 1)
        for line in (root / "production.public.env").read_text().splitlines()
        if line and not line.startswith("#")
    )
    compose = (root / "docker-compose.prod.yml").read_text()

    assert values["BILLING_KILL_SWITCH"] == "false"
    assert values["TELEGRAM_STARS_ENABLED"] == "true"
    assert values["TELEGRAM_STARS_AMOUNT_READING_SINGLE"] == "40"
    assert values["TELEGRAM_STARS_AMOUNT_READING_PACK_5"] == "200"
    assert values["TELEGRAM_STARS_AMOUNT_SUBSCRIPTION_MONTHLY"] == "280"
    assert values["SUBSCRIPTIONS_ENABLED"] == "true"
    assert compose.count("      - .env.prod\n      - production.public.env") == 6


def test_remote_deploy_migrates_before_starting_the_application_stack() -> None:
    script = (Path(__file__).parents[1] / "tools" / "deploy_prod_remote.sh").read_text()

    build = script.index("${COMPOSE} build")
    database = script.index("${COMPOSE} up -d --wait --wait-timeout 120 db")
    migration = script.index("${COMPOSE} run --rm -T --no-deps api python -m app.cli.release")
    application = script.index("${COMPOSE} up -d --no-build --wait --wait-timeout 180")

    assert build < database < migration < application
    assert "${COMPOSE} up -d --build" not in script
    assert "${COMPOSE} logs --tail=200 api" in script


def test_production_compose_exposes_stable_caddy_alias() -> None:
    compose = (Path(__file__).parents[1] / "docker-compose.prod.yml").read_text()

    assert "      web:\n        aliases:\n          - bot-globa-api" in compose


def test_remote_deploy_fails_closed_on_shared_host_preflight() -> None:
    script = (Path(__file__).parents[1] / "tools" / "deploy_prod_remote.sh").read_text()

    assert "docker network inspect web >/dev/null 2>&1" in script
    assert "docker network create web" not in script
    assert "REQUIRE_ORACLE_ROLLOUT_ZERO" in script
    assert "tools/ensure_oracle_rollout_zero.sh .env.prod" in script
    assert ".NetworkSettings.Networks.web.Aliases" in script
    assert "grep -Fq" in script
    assert "bot-globa-api" in script


def _run_rollout_zero_guard(tmp_path: Path, content: str) -> tuple[subprocess.CompletedProcess[str], Path]:
    env_file = tmp_path / ".env.prod"
    env_file.write_text(content)
    script = Path(__file__).parents[1] / "tools" / "ensure_oracle_rollout_zero.sh"
    result = subprocess.run(
        ["bash", str(script), str(env_file)],
        text=True,
        capture_output=True,
        check=False,
    )
    return result, env_file


def test_rollout_zero_guard_bootstraps_only_a_missing_value(tmp_path: Path) -> None:
    result, env_file = _run_rollout_zero_guard(tmp_path, "APP_ENV=production\n")

    assert result.returncode == 0
    assert env_file.read_text().splitlines().count("ORACLE_ROLLOUT_PERCENTAGE=0") == 1
    assert result.stdout == ""
    assert result.stderr == ""


def test_rollout_zero_guard_preserves_one_explicit_zero(tmp_path: Path) -> None:
    original = "APP_ENV=production\nORACLE_ROLLOUT_PERCENTAGE=0\n"
    result, env_file = _run_rollout_zero_guard(tmp_path, original)

    assert result.returncode == 0
    assert env_file.read_text() == original


@pytest.mark.parametrize(
    "content",
    [
        "APP_ENV=production\nORACLE_ROLLOUT_PERCENTAGE=1\n",
        "ORACLE_ROLLOUT_PERCENTAGE=0\nORACLE_ROLLOUT_PERCENTAGE=0\n",
        "ORACLE_ROLLOUT_PERCENTAGE=0\nORACLE_ROLLOUT_PERCENTAGE=1\n",
    ],
)
def test_rollout_zero_guard_refuses_nonzero_or_ambiguous_values(
    tmp_path: Path, content: str
) -> None:
    result, env_file = _run_rollout_zero_guard(tmp_path, content)

    assert result.returncode != 0
    assert env_file.read_text() == content
    assert result.stdout == ""


def test_public_oracle_smoke_requires_direct_https_200() -> None:
    script = (Path(__file__).parents[1] / "tools" / "smoke_prod_remote.sh").read_text()

    assert "PUBLIC_ORACLE_URL" in script
    assert "!= https://*" in script
    assert "--write-out '%{http_code}'" in script
    assert '[[ "${status}" != "200" ]]' in script
    assert "--location" not in script


def test_remote_deploy_scripts_have_valid_bash_syntax() -> None:
    root = Path(__file__).parents[1] / "tools"
    for name in (
        "deploy_prod_remote.sh",
        "ensure_oracle_rollout_zero.sh",
        "smoke_prod_remote.sh",
    ):
        subprocess.run(["bash", "-n", str(root / name)], check=True)
