from enum import Enum


class MCPToolCallStatus(str, Enum):
    SUCCESS = "success"
    AUTH_ERROR = "auth_error"
    ERROR = "error"
