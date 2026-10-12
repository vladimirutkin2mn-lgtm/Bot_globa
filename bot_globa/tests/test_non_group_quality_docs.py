from pathlib import Path


def test_non_group_quality_docs_exist() -> None:
    assert Path("docs/non_group_quality_acceptance.md").exists()
