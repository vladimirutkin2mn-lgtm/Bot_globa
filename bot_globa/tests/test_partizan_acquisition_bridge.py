"""Public Partizan acquisition bridge stays minimal and fail-closed."""

from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.acquisition import router
from app.deployment import DeploymentSettings


def _client(username: str = "NumaOracleBot") -> TestClient:
    app = FastAPI()
    app.state.deployment_settings = DeploymentSettings(telegram_bot_username=username)
    app.include_router(router)
    return TestClient(app)


def test_partizan_destination_becomes_exact_telegram_deep_link() -> None:
    experiment_id = uuid4()
    client = _client()

    response = client.get(
        "/",
        params={
            "ptz_experiment": str(experiment_id),
            "utm_source": "partizan",
            "utm_campaign": "ignored",
            "next": "https://attacker.example",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == (
        f"https://t.me/NumaOracleBot?start=ptz_{experiment_id.hex}"
    )
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "attacker.example" not in response.headers["location"]
    assert "utm_" not in response.headers["location"]


def test_explicit_acquisition_path_uses_the_same_contract() -> None:
    experiment_id = uuid4()
    client = _client()

    response = client.get(
        "/acquire/partizan",
        params={"ptz_experiment": str(experiment_id)},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"].endswith(f"?start=ptz_{experiment_id.hex}")


def test_non_partizan_landing_opens_bot_without_inventing_attribution() -> None:
    response = _client().get("/", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "https://t.me/NumaOracleBot"


def test_malformed_partizan_experiment_is_rejected_before_redirect() -> None:
    response = _client().get(
        "/",
        params={"ptz_experiment": "not-a-uuid"},
        follow_redirects=False,
    )

    assert response.status_code == 422
    assert "location" not in response.headers


def test_acquisition_route_fails_closed_until_bot_username_is_configured() -> None:
    response = _client("").get(
        "/",
        params={"ptz_experiment": str(uuid4())},
        follow_redirects=False,
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Telegram acquisition route is not configured"


def test_bot_username_is_normalized_and_validated() -> None:
    assert (
        DeploymentSettings(telegram_bot_username="@NumaOracleBot").telegram_bot_username
        == "NumaOracleBot"
    )
    with pytest.raises(ValidationError):
        DeploymentSettings(telegram_bot_username="not a bot")
    with pytest.raises(ValidationError):
        DeploymentSettings(telegram_bot_username="NumaOracle")
