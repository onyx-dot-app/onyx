from pydantic import BaseModel


class DeleteCollectionResult(BaseModel):
    success: bool


class CreateCollectionResult(BaseModel):
    success: bool


class UpdateCollectionResult(BaseModel):
    success: bool
