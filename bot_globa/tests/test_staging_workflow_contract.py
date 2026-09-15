import os
import shutil
import subprocess
from pathlib import Path


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _staging_workflow_text() -> str:
    return (
        _repository_root() / ".github" / "workflows" / "bot-globa-deploy-staging.yml"
    ).read_text(encoding="utf-8")


def test_staging_workflow_has_non_mutating_preflight_mode() -> None:
    workflow = _staging_workflow_text()

    assert "preflight_only:" in workflow
    assert "if: inputs.preflight_only" in workflow
    assert "Choose either preflight_only or smoke_only, not both." in workflow

    preflight_step = workflow.split(
        "- name: Preflight the existing staging host without changing it", maxsplit=1
    )[1].split("- name: Smoke the deployed staging release", maxsplit=1)[0]

    assert "bash tools/preflight_staging_remote.sh" in preflight_step
    assert "docker network inspect web" in preflight_step
    for forbidden in (
        "deploy_staging_remote.sh",
        "RELEASE_CODE_SHA",
        "docker compose",
        "rsync",
        "migrate",
    ):
        assert forbidden not in preflight_step


def test_staging_mutating_modes_are_disabled_during_preflight() -> None:
    workflow = _staging_workflow_text()

    assert "if: ${{ inputs.smoke_only && !inputs.preflight_only }}" in workflow
    assert "if: ${{ !inputs.smoke_only && !inputs.preflight_only }}" in workflow


def test_staging_workflow_requires_public_https_url_outside_preflight() -> None:
    workflow = _staging_workflow_text()

    validation_step = workflow.split(
        "- name: Validate public staging URL for smoke/deploy", maxsplit=1
    )[1].split("- name: Require dedicated staging SSH configuration", maxsplit=1)[0]

    assert 'if [[ "${PREFLIGHT_ONLY}" == "true" ]]' in validation_step
    assert 'if [[ -z "${PUBLIC_STAGING_URL}" ]]' in validation_step
    assert '"${PUBLIC_STAGING_URL}" != https://*' in validation_step
    assert "example.invalid" in validation_step
    assert "public_staging_url is required for staging smoke/deploy." in validation_step


def test_staging_smoke_rejects_missing_public_url_before_remote_calls() -> None:
    bash = shutil.which("bash")
    assert bash is not None

    script = _repository_root() / "bot_globa" / "tools" / "smoke_staging_remote.sh"
    env = {
        **os.environ,
        "DEPLOY_HOST": "staging-host.invalid",
        "PUBLIC_STAGING_URL": "",
        "PATH": "",
    }
    result = subprocess.run(
        [bash, str(script)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "PUBLIC_STAGING_URL is required" in output
    assert "Staging container health" not in output
