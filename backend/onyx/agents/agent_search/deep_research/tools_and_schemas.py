import json
from typing import List
from typing import Type
from typing import TypeVar
from typing import Union

from pydantic import BaseModel
from pydantic import Field
from pydantic import ValidationError

T = TypeVar("T", bound=BaseModel)


class SearchQueryList(BaseModel):
    query: List[str] = Field(
        description="A list of search queries to be used for Onyx research."
    )
    rationale: str = Field(
        description="A brief explanation of why these queries are relevant to the research topic."
    )


class Reflection(BaseModel):
    is_sufficient: bool = Field(
        description="Whether the provided summaries are sufficient to answer the user's question."
    )
    knowledge_gap: str = Field(
        description="A description of what information is missing or needs clarification."
    )
    follow_up_queries: List[str] = Field(
        description="A list of follow-up queries to address the knowledge gap."
    )


class Plan(BaseModel):
    """Plan to follow in future"""

    steps: List[str] = Field(
        description="different steps to follow, should be in sorted order"
    )


class Response(BaseModel):
    """Response to user."""

    response: str


class Act(BaseModel):
    """Action to perform."""

    action: Union[Response, Plan] = Field(
        description="Action to perform. If you want to respond to user, use Response. "
        "If you need to further use tools to get the answer, use Plan."
    )


def json_to_pydantic(json_string: str, pydantic_class: Type[T]) -> T:
    """
    Convert a JSON string to a Pydantic model instance.

    Args:
        json_string: JSON string to parse
        pydantic_class: Pydantic model class to instantiate

    Returns:
        Instance of the pydantic_class

    Raises:
        json.JSONDecodeError: If json_string is invalid JSON
        ValidationError: If JSON data doesn't match the Pydantic model schema
        TypeError: If pydantic_class is not a Pydantic model
    """
    # Validate that the class is a Pydantic model
    if not (isinstance(pydantic_class, type) and issubclass(pydantic_class, BaseModel)):
        raise TypeError(
            f"pydantic_class must be a Pydantic BaseModel subclass, got {type(pydantic_class)}"
        )

    artifacts = ["json", "```"]
    json_string = json_string.replace(artifacts[0], "").replace(artifacts[1], "")

    # Parse JSON string to dictionary
    try:
        data = json.loads(json_string)
    except json.JSONDecodeError as e:
        raise json.JSONDecodeError(f"Invalid JSON string: {e.msg}", e.doc, e.pos)

    # Create and validate Pydantic model instance
    try:
        return pydantic_class.model_validate(data)
    except ValidationError as e:
        print(f"JSON data doesn't match {pydantic_class.__name__} schema: {e}")
        raise e
