import math
from collections.abc import Callable

import httpx
from pydantic import JsonValue

from onyx.llm.decisions.models import (
    ChoiceAnswer,
    ChoiceProbability,
    ChoiceQuestion,
    DecisionAnswer,
    DecisionProvider,
    DecisionRequest,
    DecisionResponse,
    DecisionUsage,
    PredicateAnswer,
    ScoreAnswer,
    ScoreProbability,
    ScoreQuestion,
    SystemOneResponse,
    ZoomResponse,
)
from onyx.tracing.flows import LLMFlow
from onyx.tracing.framework.traces import TraceContentMode
from onyx.tracing.llm_utils import traced_llm_call

_ENDPOINTS = {
    DecisionProvider.TYPESAFE: ("https://api.typesafe.ai/v1", "systemone"),
    DecisionProvider.ZOOM_AI: ("https://api.zoom.us/v2", "aiservices/decisions/decide"),
    DecisionProvider.OPENAI: ("https://api.openai.com/v1", "decisions"),
    DecisionProvider.OPENROUTER: ("https://openrouter.ai/api/alpha", "decisions"),
    DecisionProvider.VERCEL_AI_GATEWAY: (
        "https://ai-gateway.vercel.sh/v1",
        "decisions",
    ),
}


def _system_one_request(request: DecisionRequest, model: str) -> dict[str, JsonValue]:
    questions: dict[str, JsonValue] = {}
    for question in request.questions:
        wire_question: dict[str, JsonValue] = {"instructions": question.instructions}
        if question.type == "predicate":
            wire_question["type"] = "noul"
        elif question.type == "choice":
            wire_question["type"] = "choice"
            wire_question["criteria"] = {
                choice.value: choice.description for choice in question.choices
            }
        else:
            wire_question["type"] = "score"
            wire_question["criteria"] = [
                f"{level.label}: {level.description}"
                if level.description
                else level.label
                for level in question.levels
            ]
        questions[question.name] = wire_question
    return {"state": request.input, "questions": questions, "model": model}


def _system_one_response(payload: object) -> DecisionResponse:
    parsed = SystemOneResponse.model_validate(payload)
    answers: list[DecisionAnswer] = []
    for name, answer in parsed.answers.items():
        if answer.type == "noul":
            answers.append(PredicateAnswer(name=name, probability=answer.noul))
        elif answer.type == "choice":
            answers.append(
                ChoiceAnswer(
                    name=name,
                    choice=answer.choice,
                    confidence=answer.confidence,
                    probabilities=[
                        ChoiceProbability(value=value, probability=probability)
                        for value, probability in answer.probabilities.items()
                    ],
                )
            )
        else:
            answers.append(
                ScoreAnswer(
                    name=name,
                    score=answer.score,
                    confidence=answer.confidence,
                    probabilities=[
                        ScoreProbability(
                            value=int(value),
                            label=answer.legend[value],
                            probability=probability,
                        )
                        for value, probability in answer.probabilities.items()
                    ],
                )
            )
    return DecisionResponse(model=parsed.model, answers=answers, usage=parsed.usage)


def _validate_answers(
    request: DecisionRequest, response: DecisionResponse
) -> DecisionResponse:
    by_name = {answer.name: answer for answer in response.answers}
    if len(by_name) != len(response.answers) or set(by_name) != {
        question.name for question in request.questions
    }:
        raise ValueError(
            "Decision response does not match the requested question names"
        )
    for question in request.questions:
        answer = by_name[question.name]
        if answer.type == "refusal":
            continue
        if answer.type != question.type:
            raise ValueError("Decision answer type does not match its question")
        if isinstance(answer, ChoiceAnswer) and isinstance(question, ChoiceQuestion):
            values = {choice.value for choice in question.choices}
            probabilities = answer.probabilities
            if (
                answer.choice not in values
                or {item.value for item in probabilities} != values
                or len(probabilities) != len(values)
            ):
                raise ValueError(
                    "Decision choice distribution does not match its choices"
                )
        elif isinstance(answer, ScoreAnswer) and isinstance(question, ScoreQuestion):
            if (
                {item.value for item in answer.probabilities}
                != set(range(len(question.levels)))
                or len(answer.probabilities) != len(question.levels)
                or not 0 <= answer.score <= len(question.levels) - 1
            ):
                raise ValueError(
                    "Decision score distribution does not match its levels"
                )
        if isinstance(answer, (ChoiceAnswer, ScoreAnswer)) and not math.isclose(
            sum(item.probability for item in answer.probabilities), 1.0, abs_tol=1e-5
        ):
            raise ValueError("Decision probabilities must sum to one")
    response.answers = [by_name[question.name] for question in request.questions]
    return response


class DecisionClient:
    def __init__(
        self,
        provider: DecisionProvider,
        model: str,
        api_key: str,
        api_base: str | None = None,
        timeout: float = 30.0,
        extra_headers: dict[str, str] | None = None,
        api_key_resolver: Callable[[], str] | None = None,
    ) -> None:
        self.provider = provider
        self._api_key_resolver = api_key_resolver
        self.model = model
        base, path = _ENDPOINTS[provider]
        if provider == DecisionProvider.ZOOM_AI and api_base:
            raise ValueError("Zoom Decisions uses its fixed hosted endpoint")
        base = (api_base or base).rstrip("/")
        if provider == DecisionProvider.OPENROUTER and base.endswith("/v1"):
            base = base.removesuffix("/v1") + "/alpha"
        self.url = f"{base}/{path}"
        self.timeout = timeout
        self._headers = {
            **(extra_headers or {}),
            "Authorization": f"Bearer {api_key}",
        }

    def decide(self, request: DecisionRequest, *, flow: LLMFlow) -> DecisionResponse:
        system_one = self.provider in {
            DecisionProvider.TYPESAFE,
            DecisionProvider.OPENROUTER,
        }
        body = (
            _system_one_request(request, self.model)
            if system_one
            else {
                **request.model_dump(mode="json", exclude_none=True),
                "model": self.model,
            }
        )
        with traced_llm_call(
            flow=flow,
            model=self.model,
            provider=self.provider.value,
            input_messages=body,
        ) as span:
            with httpx.Client(timeout=self.timeout) as client:
                headers = dict(self._headers)
                if self._api_key_resolver:
                    headers["Authorization"] = f"Bearer {self._api_key_resolver()}"
                result = client.post(self.url, json=body, headers=headers)
                result.raise_for_status()
            if system_one:
                response = _system_one_response(result.json())
            elif self.provider == DecisionProvider.ZOOM_AI:
                zoom = ZoomResponse.model_validate(result.json())
                response = DecisionResponse(
                    model=zoom.model,
                    answers=zoom.answers,
                    usage=(
                        DecisionUsage(
                            input_tokens=zoom.usage.input_units,
                            output_tokens=zoom.usage.output_units,
                        )
                        if zoom.usage and zoom.usage.unit_type == "tokens"
                        else None
                    ),
                )
            else:
                response = DecisionResponse.model_validate(result.json())
            response = _validate_answers(request, response)
            if span.content_mode == TraceContentMode.FULL:
                span.span_data.output = [response.model_dump(mode="json")]
            if response.usage:
                span.span_data.usage = response.usage.model_dump()
            span.span_data.routed_model = response.model
            return response
