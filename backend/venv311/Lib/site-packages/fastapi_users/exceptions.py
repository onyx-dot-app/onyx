from typing import Any


class FastAPIUsersException(Exception):
    pass


class InvalidID(FastAPIUsersException):
    pass


class UserAlreadyExists(FastAPIUsersException):
    pass


class UserNotExists(FastAPIUsersException):
    pass


class UserInactive(FastAPIUsersException):
    pass


class UserAlreadyVerified(FastAPIUsersException):
    pass


class InvalidVerifyToken(FastAPIUsersException):
    pass


class InvalidResetPasswordToken(FastAPIUsersException):
    pass


class InvalidPasswordException(FastAPIUsersException):
    def __init__(self, reason: Any) -> None:
        self.reason = reason
