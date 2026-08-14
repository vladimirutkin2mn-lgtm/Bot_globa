"""Isolation and syntax checks for the live-gate staging runtime."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]


def test_staging_runtime_is_separate_from_production() -> None:
    compose = (ROOT / "docker-compose.staging.yml").read_text()
    public_env = (ROOT / "staging.public.env").read_text()
    example = (ROOT / ".env.staging.example").read_text()
    ignored = (ROOT / ".gitignore").read_text().splitlines()

    assert "name: bot_globa_staging" in compose
    assert "bot-globa-staging-api" in compose
    assert "staging_pgdata:/var/lib/postgresql/data" in compose
    assert compose.count("      - .env.staging\n      - staging.public.env") == 6
    assert ".env.prod" not in compose
    assert "predict.mypresence.ru" not in compose

    assert "APP_ENV=staging" in example
    assert "POSTGRES_DB=bot_globa_staging" in example
    assert "sk_live_" not in example
    assert "rk_live_" not in example
    assert "predict.mypresence.ru" not in example

    assert "BILLING_ENABLED=true" in public_env
    assert "STRIPE_ENABLED=true" in public_env
    assert "YOOKASSA_ENABLED=true" in public_env
    assert "SUBSCRIPTIONS_ENABLED=true" in public_env
    assert "REFUNDS_ENABLED=true" in public_env
    assert "YOOKASSA_RECURRING_ENABLED=true" in public_env
    assert "TELEGRAM_STARS_ENABLED=false" in public_env
    assert "ADMIN_METRICS_ENABLED=true" in public_env

    assert ".env.prod" in ignored
    assert ".env.staging" in ignored
    assert ".env.staging.release" in ignored


def test_staging_deploy_is_exact_release_and_fail_closed() -> None:
    deploy = (ROOT / "tools" / "deploy_staging_remote.sh").read_text()
    smoke = (ROOT / "tools" / "smoke_staging_remote.sh").read_text()
    workflow = (
        ROOT.parent / ".github" / "workflows" / "bot-globa-deploy-staging.yml"
    ).read_text()

    assert "^[0-9a-f]{40}$" in deploy
    assert ".env.staging.release" in deploy
    assert "docker network inspect web >/dev/null 2>&1" in deploy
    assert "docker network create web" not in deploy
    assert "bot-globa-staging-api" in deploy
    assert ".env.prod" not in smoke
    assert "/admin/release-readiness" in smoke
    assert "payload['app_env'] == 'staging'" in smoke
    assert "--location" not in smoke

    assert "environment: staging" in workflow
    assert "RELEASE_CODE_SHA: ${{ github.sha }}" in workflow
    assert "bot-globa-deploy-staging" in workflow
    assert "environment: production" not in workflow

    for name in ("deploy_staging_remote.sh", "smoke_staging_remote.sh"):
        subprocess.run(["bash", "-n", str(ROOT / "tools" / name)], check=True)


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker is required for Compose validation")
def test_staging_compose_configuration_renders_without_real_secrets(tmp_path: Path) -> None:
    compose = (ROOT / "docker-compose.staging.yml").read_text()
    example = (ROOT / ".env.staging.example").read_text().replace(
        "POSTGRES_PASSWORD=", "POSTGRES_PASSWORD=ci-only", 1
    )
    public_env = (ROOT / "staging.public.env").read_text()

    (tmp_path / "docker-compose.staging.yml").write_text(compose)
    (tmp_path / ".env.staging").write_text(example)
    (tmp_path / "staging.public.env").write_text(public_env)
    (tmp_path / ".env.staging.release").write_text(
        f"RELEASE_CODE_SHA={'a' * 40}\nRELEASE_CHECKLIST_VERSION=m5-live-v1\n"
    )

    environment = os.environ.copy()
    environment["POSTGRES_PASSWORD"] = "ci-only"
    subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            "docker-compose.staging.yml",
            "--env-file",
            ".env.staging",
            "--env-file",
            ".env.staging.release",
            "config",
            "--quiet",
        ],
        cwd=tmp_path,
        env=environment,
        check=True,
    )
