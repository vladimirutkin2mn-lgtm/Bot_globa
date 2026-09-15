from pathlib import Path


def _staging_workflow_text() -> str:
    repository_root = Path(__file__).resolve().parents[2]
    return (repository_root / ".github" / "workflows" / "bot-globa-deploy-staging.yml").read_text(
        encoding="utf-8"
    )


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
