"""An OpenAI-compatible provider is reached by pointing the client at another base URL.

The adapter speaks the Responses API. Any provider implementing it can serve the same
strict-schema contract, so the only thing that varies is where the client sends requests.
"""

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.providers.llm.factory import create_llm_client
from app.providers.llm.openai import OpenAILLMClient


def _configured(settings: Settings, **overrides: object) -> Settings:
    return settings.model_copy(
        update={
            "llm_provider": "openai",
            "openai_api_key": SecretStr("test-key"),
            "llm_model": "some-model",
            **overrides,
        }
    )


def test_the_default_base_url_is_the_providers_own(settings: Settings) -> None:
    client = create_llm_client(_configured(settings))

    assert isinstance(client, OpenAILLMClient)
    assert "api.openai.com" in str(client._client.base_url)


def test_a_configured_base_url_redirects_every_request(settings: Settings) -> None:
    client = create_llm_client(_configured(settings, llm_base_url="https://api.x.ai/v1"))

    assert isinstance(client, OpenAILLMClient)
    assert str(client._client.base_url).rstrip("/") == "https://api.x.ai/v1"


def test_surrounding_whitespace_does_not_become_a_base_url(settings: Settings) -> None:
    client = create_llm_client(_configured(settings, llm_base_url="   "))

    assert isinstance(client, OpenAILLMClient)
    assert "api.openai.com" in str(client._client.base_url)


def test_an_empty_key_is_still_refused_whatever_the_base_url(settings: Settings) -> None:
    configured = _configured(
        settings, openai_api_key=SecretStr(""), llm_base_url="https://api.x.ai/v1"
    )

    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        create_llm_client(configured)
