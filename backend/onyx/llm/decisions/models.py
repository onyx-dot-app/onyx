from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DecisionProvider(StrEnum):
    TYPESAFE = "typesafe"
    ZOOM_AI = "zoom_ai"
    OPENAI = "openai"
    OPENROUTER = "openrouter"
    VERCEL_AI_GATEWAY = "vercel_ai_gateway"


class DecisionModel(BaseModel):
    model_config = ConfigDict(strict=True, allow_inf_nan=False)


class PredicateQuestion(DecisionModel):
    type: Literal["predicate"] = "predicate"
    name: str = Field(min_length=1)
    instructions: str = Field(min_length=1)


class DecisionChoice(DecisionModel):
    value: str = Field(min_length=1)
    description: str | None = None


class ChoiceQuestion(DecisionModel):
    type: Literal["choice"] = "choice"
    name: str = Field(min_length=1)
    instructions: str = Field(min_length=1)
    choices: list[DecisionChoice] = Field(min_length=2, max_length=255)

    @model_validator(mode="after")
    def unique_choices(self) -> Self:
        if len({choice.value for choice in self.choices}) != len(self.choices):
            raise ValueError("Decision choice values must be unique")
        return self


class ScoreLevel(DecisionModel):
    label: str = Field(min_length=1)
    description: str | None = None


class ScoreQuestion(DecisionModel):
    type: Literal["score"] = "score"
    name: str = Field(min_length=1)
    instructions: str = Field(min_length=1)
    levels: list[ScoreLevel] = Field(min_length=2, max_length=10)


DecisionQuestion = Annotated[
    PredicateQuestion | ChoiceQuestion | ScoreQuestion, Field(discriminator="type")
]


class DecisionRequest(DecisionModel):
    input: str
    questions: list[DecisionQuestion] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique_names(self) -> Self:
        if len({question.name for question in self.questions}) != len(self.questions):
            raise ValueError("Decision question names must be unique")
        return self


Probability = Annotated[float, Field(ge=0, le=1)]


class PredicateAnswer(DecisionModel):
    type: Literal["predicate"] = "predicate"
    name: str
    probability: Probability


class ChoiceProbability(DecisionModel):
    value: str
    probability: Probability


class ChoiceAnswer(DecisionModel):
    type: Literal["choice"] = "choice"
    name: str
    choice: str
    confidence: float
    probabilities: list[ChoiceProbability]


class ScoreProbability(DecisionModel):
    value: int
    label: str
    probability: Probability


class ScoreAnswer(DecisionModel):
    type: Literal["score"] = "score"
    name: str
    score: float
    confidence: float
    probabilities: list[ScoreProbability]


class RefusalAnswer(DecisionModel):
    type: Literal["refusal"] = "refusal"
    name: str


DecisionAnswer = Annotated[
    PredicateAnswer | ChoiceAnswer | ScoreAnswer | RefusalAnswer,
    Field(discriminator="type"),
]


class DecisionUsage(DecisionModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class DecisionResponse(DecisionModel):
    model: str
    answers: list[DecisionAnswer]
    usage: DecisionUsage | None = None


class SystemOneNoulAnswer(DecisionModel):
    type: Literal["noul"]
    noul: Probability


class SystemOneChoiceAnswer(DecisionModel):
    type: Literal["choice"]
    choice: str
    confidence: float
    probabilities: dict[str, Probability]


class SystemOneScoreAnswer(DecisionModel):
    type: Literal["score"]
    score: float
    confidence: float
    probabilities: dict[str, Probability]
    legend: dict[str, str]

    @model_validator(mode="after")
    def valid_level_keys(self) -> Self:
        if set(self.legend) != set(self.probabilities) or any(
            str(int(key)) != key for key in self.probabilities
        ):
            raise ValueError(
                "Decision score legend must match its indexed probabilities"
            )
        return self


class SystemOneResponse(DecisionModel):
    model: str
    answers: dict[
        str,
        Annotated[
            SystemOneNoulAnswer | SystemOneChoiceAnswer | SystemOneScoreAnswer,
            Field(discriminator="type"),
        ],
    ]
    usage: DecisionUsage | None = None


class ZoomUsage(DecisionModel):
    input_units: int = Field(ge=0)
    output_units: int = Field(ge=0)
    unit_type: str


class ZoomResponse(DecisionModel):
    model: str
    answers: list[DecisionAnswer]
    usage: ZoomUsage | None = None
