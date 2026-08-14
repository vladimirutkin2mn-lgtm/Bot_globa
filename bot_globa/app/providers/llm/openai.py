"""Official OpenAI Responses API adapter."""

import time
from typing import cast

import openai
from openai import AsyncOpenAI
from openai.types.responses import (
    EasyInputMessageParam,
    ResponseInputParam,
    ResponseTextConfigParam,
)

from app.providers.llm.base import (
    LLMAuthenticationError,
    LLMCompletion,
    LLMInvalidRequestError,
    LLMRateLimitError,
    LLMRequest,
    LLMTimeoutError,
    LLMTransientError,
    LLMUnexpectedError,
)

_UNSUPPORTED_STRICT_SCHEMA_KEYS = frozenset(
    {
        "default",
        "examples",
        "format",
        "maxItems",
        "maxLength",
        "maximum",
        "minItems",
        "minLength",
        "minimum",
        "pattern",
        "title",
    }
)


def openai_strict_schema(value: object) -> object:
    """Remove validation keywords unsupported by OpenAI strict structured outputs.

    The complete Pydantic contract is always applied after receipt, so simplifying the
    provider hint does not weaken domain validation — but it does hide the rules from the
    model, which then breaks them and has its answer rejected for a limit it was never
    shown. Whatever is removed here has to be restated in words: see `schema_constraints`.
    """
    if isinstance(value, dict):
        converted = {
            key: openai_strict_schema(item)
            for key, item in value.items()
            if key not in _UNSUPPORTED_STRICT_SCHEMA_KEYS
        }
        properties = converted.get("properties")
        if converted.get("type") == "object" and isinstance(properties, dict):
            converted["required"] = list(properties)
            converted["additionalProperties"] = False
        return converted
    if isinstance(value, list):
        return [openai_strict_schema(item) for item in value]
    return value


_CONSTRAINT_WORDING = {
    "minItems": "at least {value} item(s)",
    "maxItems": "at most {value} item(s)",
    "minLength": "at least {value} character(s)",
    "maxLength": "at most {value} character(s)",
    "minimum": "not below {value}",
    "maximum": "not above {value}",
    "pattern": "matching the regular expression {value}",
}


def schema_constraints(schema: object) -> tuple[str, ...]:
    """State, in words, every rule strict mode forced out of the schema.

    Derived from the schema rather than written by hand so the wording cannot drift from
    the contract it describes: a limit added to a Pydantic model appears here by itself.
    """

    found: list[str] = []
    _collect_constraints(schema, (), found)
    return tuple(sorted(found))


def _collect_constraints(value: object, path: tuple[str, ...], found: list[str]) -> None:
    if isinstance(value, list):
        for item in value:
            _collect_constraints(item, path, found)
        return
    if not isinstance(value, dict):
        return
    described = [
        _CONSTRAINT_WORDING[key].format(value=value[key])
        for key in _CONSTRAINT_WORDING
        if key in value
    ]
    if described and path:
        found.append(f"{'.'.join(path)}: {', '.join(described)}")
    for key, item in value.items():
        if key == "properties" and isinstance(item, dict):
            for name, child in item.items():
                _collect_constraints(child, (*path, str(name)), found)
        elif key in {"items", "prefixItems"}:
            _collect_constraints(item, (*path, "each item"), found)
        elif key in {"$defs", "definitions"} and isinstance(item, dict):
            # Nested models live here and are reached by `$ref`, so each definition is
            # named after itself; without this their limits would never be stated.
            for name, child in item.items():
                _collect_constraints(child, (str(name),), found)
        elif key in {"anyOf", "allOf", "oneOf"}:
            _collect_constraints(item, path, found)


def _with_constraints(request: LLMRequest) -> str:
    """Append the rules the strict schema cannot carry to the request itself.

    Without this the model is judged against limits it was never given — the failure that
    made every persona answer "не удалось завершить разбор" in production.
    """

    constraints = schema_constraints(request.schema)
    if not constraints:
        return request.user_prompt
    rules = "\n".join(f"- {line}" for line in constraints)
    return (
        f"{request.user_prompt}\n\n"
        "The schema cannot express these limits, and the answer is rejected if any is "
        f"broken:\n{rules}"
    )


class OpenAILLMClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_seconds: float,
        max_attempts: int,
        client: AsyncOpenAI | None = None,
        base_url: str | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("OpenAI API key is required")
        # A base URL lets an OpenAI-compatible provider serve the same Responses API
        # contract. The strict schema and the repair retry are unchanged either way.
        self._client: AsyncOpenAI = client or AsyncOpenAI(
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=0,
            base_url=base_url or None,
        )
        self._model, self._timeout, self._max_attempts = model, timeout_seconds, max_attempts

    async def aclose(self) -> None:
        await self._client.close()

    async def generate_structured(self, request: LLMRequest) -> LLMCompletion:
        started = time.monotonic()
        for attempt in range(1, self._max_attempts + 1):
            try:
                system_message: EasyInputMessageParam = {
                    "type": "message",
                    "role": "system",
                    "content": request.system_prompt,
                }
                user_message: EasyInputMessageParam = {
                    "type": "message",
                    "role": "user",
                    "content": _with_constraints(request),
                }
                input_messages: ResponseInputParam = [system_message, user_message]
                converted_schema = cast("dict[str, object]", openai_strict_schema(request.schema))
                text_config: ResponseTextConfigParam = {
                    "format": {
                        "type": "json_schema",
                        "name": "structured_result",
                        "strict": True,
                        "schema": converted_schema,
                    }
                }
                response = await self._client.responses.create(
                    model=self._model,
                    input=input_messages,
                    text=text_config,
                    store=False,
                    timeout=self._timeout,
                )
                usage = getattr(response, "usage", None)
                return LLMCompletion(
                    payload=response.output_text,
                    provider="openai",
                    model=getattr(response, "model", None) or self._model,
                    provider_request_id=getattr(response, "_request_id", None),
                    input_tokens=getattr(usage, "input_tokens", None),
                    output_tokens=getattr(usage, "output_tokens", None),
                    latency_ms=int((time.monotonic() - started) * 1000),
                )
            except openai.APITimeoutError as error:
                raise LLMTimeoutError from error
            except openai.RateLimitError as error:
                raise LLMRateLimitError from error
            except openai.AuthenticationError as error:
                raise LLMAuthenticationError from error
            except (
                openai.BadRequestError,
                openai.PermissionDeniedError,
                openai.NotFoundError,
            ) as error:
                raise LLMInvalidRequestError from error
            except (openai.APIConnectionError, openai.InternalServerError) as error:
                if attempt == self._max_attempts:
                    raise LLMTransientError from error
            except openai.OpenAIError as error:
                raise LLMUnexpectedError from error
            except Exception as error:
                raise LLMUnexpectedError from error
        raise LLMTransientError
