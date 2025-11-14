import re
from typing import Any

from pydantic import (
    BaseModel,
    Field,
    field_validator,
    model_validator,
)

from onyx.db.models import StandardAnswer as StandardAnswerModel
from onyx.db.models import StandardAnswerCategory as StandardAnswerCategoryModel


class StandardAnswerCategoryCreationRequest(BaseModel):
    name: str = Field(description="Название создаваемой категории стандартных ответов")


class StandardAnswerCategory(BaseModel):
    id: int = Field(description="Уникальный идентификатор категории")
    name: str = Field(description="Название категории стандартных ответов")

    @classmethod
    def from_model(
        cls, standard_answer_category: StandardAnswerCategoryModel
    ) -> "StandardAnswerCategory":
        return cls(
            id=standard_answer_category.id,
            name=standard_answer_category.name,
        )


class StandardAnswer(BaseModel):
    id: int = Field(description="Уникальный идентификатор стандартного ответа")
    keyword: str = Field(description="Ключевое слово или regex-паттерн для поиска")
    answer: str = Field(description="Стандартный ответ, который будет возвращен при совпадении")
    categories: list[int] = Field(description="Список идентификаторов категорий для ответа")
    match_regex: bool = Field(description="Флаг использования regex")
    match_any_keywords: bool = Field(description="Флаг совпадения с любым ключевым словом")

    @classmethod
    def from_model(cls, standard_answer_model: StandardAnswerModel) -> "StandardAnswer":
        categories_data = []
        for standard_answer_category_model in standard_answer_model.categories:
            categories_data.append(
                StandardAnswerCategory.from_model(
                    standard_answer_category_model
                )
            )

        return cls(
            id=standard_answer_model.id,
            keyword=standard_answer_model.keyword,
            answer=standard_answer_model.answer,
            match_regex=standard_answer_model.match_regex,
            match_any_keywords=standard_answer_model.match_any_keywords,
            categories=categories_data,
        )


class StandardAnswerCreationRequest(BaseModel):
    keyword: str = Field(description="Ключевое слово или regex-паттерн для поиска")
    answer: str = Field(description="Стандартный ответ, который будет возвращен при совпадении")
    categories: list[int] = Field(description="Список идентификаторов категорий для ответа")
    match_regex: bool = Field(description="Флаг использования regex")
    match_any_keywords: bool = Field(description="Флаг совпадения с любым ключевым словом")

    @field_validator("categories", mode="before")
    @classmethod
    def validate_categories(cls, value: list[int]) -> list[int]:
        if len(value) < 1:
            raise ValueError(
                "К стандартному ответу должна быть прикреплена хотя бы одна категория"
            )
        return value

    @model_validator(mode="after")
    def validate_only_match_any_if_not_regex(self) -> Any:
        if self.match_regex and self.match_any_keywords:
            raise ValueError(
                "Совпадение с любым ключевым словом доступно только в keyword режиме, не в regex режиме"
            )

        return self

    @model_validator(mode="after")
    def validate_keyword_if_regex(self) -> Any:
        if not self.match_regex:
            return self

        try:
            re.compile(self.keyword)
            return self
        except re.error as err:
            if isinstance(err.pattern, bytes):
                error_msg = f'Неверный regex паттерн r"{err.pattern.decode()}" в `keyword`: {err.msg}'
                raise ValueError(error_msg)
            else:
                if err.pattern is not None:
                    pattern = f'r"{err.pattern}"'
                else:
                    pattern = ""

                error_msg = " ".join(["Неверный regex паттерн", pattern, f"в `keyword`: {err.msg}"])
                raise ValueError(error_msg)
