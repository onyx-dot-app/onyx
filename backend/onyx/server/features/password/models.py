from pydantic import BaseModel


class UserResetRequest(BaseModel):
    user_email: str


class UserResetResponse(BaseModel):
    user_id: str
    new_password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str
