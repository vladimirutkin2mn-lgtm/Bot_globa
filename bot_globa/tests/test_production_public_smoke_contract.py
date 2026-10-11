from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "bot-globa-ci.yml"


def test_automatic_main_deploy_checks_documented_public_oracle_route() -> None:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")

    assert "PUBLIC_ORACLE_URL: https://predict.mypresence.ru" in workflow
    assert 'RUN_SMOKE: "1"' in workflow
