# Generated from microvm/proto/sandboxd/v1/sandboxd.proto (blob c8c2f64ae370f821e8f903af89b27843d517ab45)
# at commit d998b6399b by backend/onyx/microvm/generated/regenerate.sh. Do not edit.
import datetime

from google.protobuf import duration_pb2 as _duration_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ErrorReason(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ERROR_REASON_UNSPECIFIED: _ClassVar[ErrorReason]
    INVALID_ARGUMENT: _ClassVar[ErrorReason]
    NOT_INITIALIZED: _ClassVar[ErrorReason]
    UNAUTHENTICATED: _ClassVar[ErrorReason]
    EXECUTION_NOT_FOUND: _ClassVar[ErrorReason]
    STDIN_NOT_OPEN: _ClassVar[ErrorReason]
    EXECUTION_ENDED: _ClassVar[ErrorReason]
    START_FAILED: _ClassVar[ErrorReason]
    TOO_MANY_EXECUTIONS: _ClassVar[ErrorReason]
    INIT_FAILED: _ClassVar[ErrorReason]
    INTERNAL: _ClassVar[ErrorReason]
    KEY_NOT_SET: _ClassVar[ErrorReason]
    KEY_ALREADY_SET: _ClassVar[ErrorReason]
    MANAGED_SLOT_BUSY: _ClassVar[ErrorReason]
    MANAGED_DEVICE_MISMATCH: _ClassVar[ErrorReason]
    MANAGED_MOUNT_FAILED: _ClassVar[ErrorReason]
    FILE_NOT_FOUND: _ClassVar[ErrorReason]
    FILE_EXISTS: _ClassVar[ErrorReason]
    LIMIT_EXCEEDED: _ClassVar[ErrorReason]
    ARCHIVE_INVALID: _ClassVar[ErrorReason]
    EXECUTION_CAP_REACHED: _ClassVar[ErrorReason]

class OutputStream(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    OUTPUT_STREAM_UNSPECIFIED: _ClassVar[OutputStream]
    STDOUT: _ClassVar[OutputStream]
    STDERR: _ClassVar[OutputStream]

class Completion(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    COMPLETION_UNSPECIFIED: _ClassVar[Completion]
    EXITED: _ClassVar[Completion]
    SIGNALED: _ClassVar[Completion]
    CANCELED: _ClassVar[Completion]
    DEADLINE_EXCEEDED: _ClassVar[Completion]

class CancelSignal(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    CANCEL_SIGNAL_UNSPECIFIED: _ClassVar[CancelSignal]
    CANCEL_SIGNAL_SIGINT: _ClassVar[CancelSignal]
    CANCEL_SIGNAL_SIGTERM: _ClassVar[CancelSignal]
    CANCEL_SIGNAL_SIGKILL: _ClassVar[CancelSignal]

class ExecState(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    EXEC_STATE_UNSPECIFIED: _ClassVar[ExecState]
    RUNNING: _ClassVar[ExecState]
    ENDED: _ClassVar[ExecState]

class FileType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    FILE_TYPE_UNSPECIFIED: _ClassVar[FileType]
    FILE_TYPE_REGULAR: _ClassVar[FileType]
    FILE_TYPE_DIRECTORY: _ClassVar[FileType]
    FILE_TYPE_SYMLINK: _ClassVar[FileType]
    FILE_TYPE_OTHER: _ClassVar[FileType]

class ManagedSlot(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    MANAGED_SLOT_UNSPECIFIED: _ClassVar[ManagedSlot]
    MANAGED_SLOT_A: _ClassVar[ManagedSlot]
    MANAGED_SLOT_B: _ClassVar[ManagedSlot]
ERROR_REASON_UNSPECIFIED: ErrorReason
INVALID_ARGUMENT: ErrorReason
NOT_INITIALIZED: ErrorReason
UNAUTHENTICATED: ErrorReason
EXECUTION_NOT_FOUND: ErrorReason
STDIN_NOT_OPEN: ErrorReason
EXECUTION_ENDED: ErrorReason
START_FAILED: ErrorReason
TOO_MANY_EXECUTIONS: ErrorReason
INIT_FAILED: ErrorReason
INTERNAL: ErrorReason
KEY_NOT_SET: ErrorReason
KEY_ALREADY_SET: ErrorReason
MANAGED_SLOT_BUSY: ErrorReason
MANAGED_DEVICE_MISMATCH: ErrorReason
MANAGED_MOUNT_FAILED: ErrorReason
FILE_NOT_FOUND: ErrorReason
FILE_EXISTS: ErrorReason
LIMIT_EXCEEDED: ErrorReason
ARCHIVE_INVALID: ErrorReason
EXECUTION_CAP_REACHED: ErrorReason
OUTPUT_STREAM_UNSPECIFIED: OutputStream
STDOUT: OutputStream
STDERR: OutputStream
COMPLETION_UNSPECIFIED: Completion
EXITED: Completion
SIGNALED: Completion
CANCELED: Completion
DEADLINE_EXCEEDED: Completion
CANCEL_SIGNAL_UNSPECIFIED: CancelSignal
CANCEL_SIGNAL_SIGINT: CancelSignal
CANCEL_SIGNAL_SIGTERM: CancelSignal
CANCEL_SIGNAL_SIGKILL: CancelSignal
EXEC_STATE_UNSPECIFIED: ExecState
RUNNING: ExecState
ENDED: ExecState
FILE_TYPE_UNSPECIFIED: FileType
FILE_TYPE_REGULAR: FileType
FILE_TYPE_DIRECTORY: FileType
FILE_TYPE_SYMLINK: FileType
FILE_TYPE_OTHER: FileType
MANAGED_SLOT_UNSPECIFIED: ManagedSlot
MANAGED_SLOT_A: ManagedSlot
MANAGED_SLOT_B: ManagedSlot

class HealthRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class HealthResponse(_message.Message):
    __slots__ = ("initialized", "version", "guest_time", "generation", "sandbox_id", "running_executions", "initialized_at", "uptime", "key_set")
    INITIALIZED_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    GUEST_TIME_FIELD_NUMBER: _ClassVar[int]
    GENERATION_FIELD_NUMBER: _ClassVar[int]
    SANDBOX_ID_FIELD_NUMBER: _ClassVar[int]
    RUNNING_EXECUTIONS_FIELD_NUMBER: _ClassVar[int]
    INITIALIZED_AT_FIELD_NUMBER: _ClassVar[int]
    UPTIME_FIELD_NUMBER: _ClassVar[int]
    KEY_SET_FIELD_NUMBER: _ClassVar[int]
    initialized: bool
    version: str
    guest_time: _timestamp_pb2.Timestamp
    generation: int
    sandbox_id: str
    running_executions: int
    initialized_at: _timestamp_pb2.Timestamp
    uptime: _duration_pb2.Duration
    key_set: bool
    def __init__(self, initialized: bool = ..., version: _Optional[str] = ..., guest_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., generation: _Optional[int] = ..., sandbox_id: _Optional[str] = ..., running_executions: _Optional[int] = ..., initialized_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., uptime: _Optional[_Union[datetime.timedelta, _duration_pb2.Duration, _Mapping]] = ..., key_set: bool = ...) -> None: ...

class SetKeyRequest(_message.Message):
    __slots__ = ("key", "egress_ca_pem")
    KEY_FIELD_NUMBER: _ClassVar[int]
    EGRESS_CA_PEM_FIELD_NUMBER: _ClassVar[int]
    key: str
    egress_ca_pem: bytes
    def __init__(self, key: _Optional[str] = ..., egress_ca_pem: _Optional[bytes] = ...) -> None: ...

class SetKeyResponse(_message.Message):
    __slots__ = ("already_set",)
    ALREADY_SET_FIELD_NUMBER: _ClassVar[int]
    already_set: bool
    def __init__(self, already_set: bool = ...) -> None: ...

class InitRequest(_message.Message):
    __slots__ = ("host_time", "entropy", "env", "session_ids", "generation", "sandbox_id", "scratch_bytes")
    class EnvEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    HOST_TIME_FIELD_NUMBER: _ClassVar[int]
    ENTROPY_FIELD_NUMBER: _ClassVar[int]
    ENV_FIELD_NUMBER: _ClassVar[int]
    SESSION_IDS_FIELD_NUMBER: _ClassVar[int]
    GENERATION_FIELD_NUMBER: _ClassVar[int]
    SANDBOX_ID_FIELD_NUMBER: _ClassVar[int]
    SCRATCH_BYTES_FIELD_NUMBER: _ClassVar[int]
    host_time: _timestamp_pb2.Timestamp
    entropy: bytes
    env: _containers.ScalarMap[str, str]
    session_ids: _containers.RepeatedScalarFieldContainer[str]
    generation: int
    sandbox_id: str
    scratch_bytes: int
    def __init__(self, host_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., entropy: _Optional[bytes] = ..., env: _Optional[_Mapping[str, str]] = ..., session_ids: _Optional[_Iterable[str]] = ..., generation: _Optional[int] = ..., sandbox_id: _Optional[str] = ..., scratch_bytes: _Optional[int] = ...) -> None: ...

class InitResponse(_message.Message):
    __slots__ = ("clock_step", "entropy_credited", "grown", "version", "attached", "relay_reset", "egress_ca_installed")
    CLOCK_STEP_FIELD_NUMBER: _ClassVar[int]
    ENTROPY_CREDITED_FIELD_NUMBER: _ClassVar[int]
    GROWN_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    ATTACHED_FIELD_NUMBER: _ClassVar[int]
    RELAY_RESET_FIELD_NUMBER: _ClassVar[int]
    EGRESS_CA_INSTALLED_FIELD_NUMBER: _ClassVar[int]
    clock_step: _duration_pb2.Duration
    entropy_credited: bool
    grown: _containers.RepeatedCompositeFieldContainer[GrownFS]
    version: str
    attached: bool
    relay_reset: bool
    egress_ca_installed: bool
    def __init__(self, clock_step: _Optional[_Union[datetime.timedelta, _duration_pb2.Duration, _Mapping]] = ..., entropy_credited: bool = ..., grown: _Optional[_Iterable[_Union[GrownFS, _Mapping]]] = ..., version: _Optional[str] = ..., attached: bool = ..., relay_reset: bool = ..., egress_ca_installed: bool = ...) -> None: ...

class GrownFS(_message.Message):
    __slots__ = ("mount_point", "old_bytes", "new_bytes")
    MOUNT_POINT_FIELD_NUMBER: _ClassVar[int]
    OLD_BYTES_FIELD_NUMBER: _ClassVar[int]
    NEW_BYTES_FIELD_NUMBER: _ClassVar[int]
    mount_point: str
    old_bytes: int
    new_bytes: int
    def __init__(self, mount_point: _Optional[str] = ..., old_bytes: _Optional[int] = ..., new_bytes: _Optional[int] = ...) -> None: ...

class Command(_message.Message):
    __slots__ = ("argv", "cwd", "env", "stdin", "deadline", "labels", "session_id")
    class EnvEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    class LabelsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    ARGV_FIELD_NUMBER: _ClassVar[int]
    CWD_FIELD_NUMBER: _ClassVar[int]
    ENV_FIELD_NUMBER: _ClassVar[int]
    STDIN_FIELD_NUMBER: _ClassVar[int]
    DEADLINE_FIELD_NUMBER: _ClassVar[int]
    LABELS_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    argv: _containers.RepeatedScalarFieldContainer[str]
    cwd: str
    env: _containers.ScalarMap[str, str]
    stdin: bool
    deadline: _duration_pb2.Duration
    labels: _containers.ScalarMap[str, str]
    session_id: str
    def __init__(self, argv: _Optional[_Iterable[str]] = ..., cwd: _Optional[str] = ..., env: _Optional[_Mapping[str, str]] = ..., stdin: bool = ..., deadline: _Optional[_Union[datetime.timedelta, _duration_pb2.Duration, _Mapping]] = ..., labels: _Optional[_Mapping[str, str]] = ..., session_id: _Optional[str] = ...) -> None: ...

class RunRequest(_message.Message):
    __slots__ = ("command",)
    COMMAND_FIELD_NUMBER: _ClassVar[int]
    command: Command
    def __init__(self, command: _Optional[_Union[Command, _Mapping]] = ...) -> None: ...

class StartRequest(_message.Message):
    __slots__ = ("command",)
    COMMAND_FIELD_NUMBER: _ClassVar[int]
    command: Command
    def __init__(self, command: _Optional[_Union[Command, _Mapping]] = ...) -> None: ...

class StartResponse(_message.Message):
    __slots__ = ("started",)
    STARTED_FIELD_NUMBER: _ClassVar[int]
    started: ExecStarted
    def __init__(self, started: _Optional[_Union[ExecStarted, _Mapping]] = ...) -> None: ...

class ExecStarted(_message.Message):
    __slots__ = ("execution_id", "pid", "started_at", "deadline_at")
    EXECUTION_ID_FIELD_NUMBER: _ClassVar[int]
    PID_FIELD_NUMBER: _ClassVar[int]
    STARTED_AT_FIELD_NUMBER: _ClassVar[int]
    DEADLINE_AT_FIELD_NUMBER: _ClassVar[int]
    execution_id: str
    pid: int
    started_at: _timestamp_pb2.Timestamp
    deadline_at: _timestamp_pb2.Timestamp
    def __init__(self, execution_id: _Optional[str] = ..., pid: _Optional[int] = ..., started_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., deadline_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class OutputChunk(_message.Message):
    __slots__ = ("stream", "offset", "data")
    STREAM_FIELD_NUMBER: _ClassVar[int]
    OFFSET_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    stream: OutputStream
    offset: int
    data: bytes
    def __init__(self, stream: _Optional[_Union[OutputStream, str]] = ..., offset: _Optional[int] = ..., data: _Optional[bytes] = ...) -> None: ...

class OutputGap(_message.Message):
    __slots__ = ("stream", "to")
    STREAM_FIELD_NUMBER: _ClassVar[int]
    FROM_FIELD_NUMBER: _ClassVar[int]
    TO_FIELD_NUMBER: _ClassVar[int]
    stream: OutputStream
    to: int
    def __init__(self, stream: _Optional[_Union[OutputStream, str]] = ..., to: _Optional[int] = ..., **kwargs) -> None: ...

class ExecResult(_message.Message):
    __slots__ = ("completion", "exit_code", "signal", "finished_at", "stdout_bytes", "stderr_bytes")
    COMPLETION_FIELD_NUMBER: _ClassVar[int]
    EXIT_CODE_FIELD_NUMBER: _ClassVar[int]
    SIGNAL_FIELD_NUMBER: _ClassVar[int]
    FINISHED_AT_FIELD_NUMBER: _ClassVar[int]
    STDOUT_BYTES_FIELD_NUMBER: _ClassVar[int]
    STDERR_BYTES_FIELD_NUMBER: _ClassVar[int]
    completion: Completion
    exit_code: int
    signal: int
    finished_at: _timestamp_pb2.Timestamp
    stdout_bytes: int
    stderr_bytes: int
    def __init__(self, completion: _Optional[_Union[Completion, str]] = ..., exit_code: _Optional[int] = ..., signal: _Optional[int] = ..., finished_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., stdout_bytes: _Optional[int] = ..., stderr_bytes: _Optional[int] = ...) -> None: ...

class ExecEvent(_message.Message):
    __slots__ = ("started", "output", "gap", "result")
    STARTED_FIELD_NUMBER: _ClassVar[int]
    OUTPUT_FIELD_NUMBER: _ClassVar[int]
    GAP_FIELD_NUMBER: _ClassVar[int]
    RESULT_FIELD_NUMBER: _ClassVar[int]
    started: ExecStarted
    output: OutputChunk
    gap: OutputGap
    result: ExecResult
    def __init__(self, started: _Optional[_Union[ExecStarted, _Mapping]] = ..., output: _Optional[_Union[OutputChunk, _Mapping]] = ..., gap: _Optional[_Union[OutputGap, _Mapping]] = ..., result: _Optional[_Union[ExecResult, _Mapping]] = ...) -> None: ...

class StreamRequest(_message.Message):
    __slots__ = ("execution_id", "stdout_offset", "stderr_offset")
    EXECUTION_ID_FIELD_NUMBER: _ClassVar[int]
    STDOUT_OFFSET_FIELD_NUMBER: _ClassVar[int]
    STDERR_OFFSET_FIELD_NUMBER: _ClassVar[int]
    execution_id: str
    stdout_offset: int
    stderr_offset: int
    def __init__(self, execution_id: _Optional[str] = ..., stdout_offset: _Optional[int] = ..., stderr_offset: _Optional[int] = ...) -> None: ...

class InteractRequest(_message.Message):
    __slots__ = ("execution_id", "data", "close_stdin")
    EXECUTION_ID_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    CLOSE_STDIN_FIELD_NUMBER: _ClassVar[int]
    execution_id: str
    data: bytes
    close_stdin: bool
    def __init__(self, execution_id: _Optional[str] = ..., data: _Optional[bytes] = ..., close_stdin: bool = ...) -> None: ...

class InteractResponse(_message.Message):
    __slots__ = ("written",)
    WRITTEN_FIELD_NUMBER: _ClassVar[int]
    written: int
    def __init__(self, written: _Optional[int] = ...) -> None: ...

class CancelRequest(_message.Message):
    __slots__ = ("execution_id", "signal")
    EXECUTION_ID_FIELD_NUMBER: _ClassVar[int]
    SIGNAL_FIELD_NUMBER: _ClassVar[int]
    execution_id: str
    signal: CancelSignal
    def __init__(self, execution_id: _Optional[str] = ..., signal: _Optional[_Union[CancelSignal, str]] = ...) -> None: ...

class CancelResponse(_message.Message):
    __slots__ = ("result", "already_ended", "signaled")
    RESULT_FIELD_NUMBER: _ClassVar[int]
    ALREADY_ENDED_FIELD_NUMBER: _ClassVar[int]
    SIGNALED_FIELD_NUMBER: _ClassVar[int]
    result: ExecResult
    already_ended: bool
    signaled: bool
    def __init__(self, result: _Optional[_Union[ExecResult, _Mapping]] = ..., already_ended: bool = ..., signaled: bool = ...) -> None: ...

class Execution(_message.Message):
    __slots__ = ("execution_id", "state", "argv", "labels", "pid", "started_at", "deadline_at", "stdout_bytes", "stderr_bytes", "result")
    class LabelsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    EXECUTION_ID_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    ARGV_FIELD_NUMBER: _ClassVar[int]
    LABELS_FIELD_NUMBER: _ClassVar[int]
    PID_FIELD_NUMBER: _ClassVar[int]
    STARTED_AT_FIELD_NUMBER: _ClassVar[int]
    DEADLINE_AT_FIELD_NUMBER: _ClassVar[int]
    STDOUT_BYTES_FIELD_NUMBER: _ClassVar[int]
    STDERR_BYTES_FIELD_NUMBER: _ClassVar[int]
    RESULT_FIELD_NUMBER: _ClassVar[int]
    execution_id: str
    state: ExecState
    argv: _containers.RepeatedScalarFieldContainer[str]
    labels: _containers.ScalarMap[str, str]
    pid: int
    started_at: _timestamp_pb2.Timestamp
    deadline_at: _timestamp_pb2.Timestamp
    stdout_bytes: int
    stderr_bytes: int
    result: ExecResult
    def __init__(self, execution_id: _Optional[str] = ..., state: _Optional[_Union[ExecState, str]] = ..., argv: _Optional[_Iterable[str]] = ..., labels: _Optional[_Mapping[str, str]] = ..., pid: _Optional[int] = ..., started_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., deadline_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., stdout_bytes: _Optional[int] = ..., stderr_bytes: _Optional[int] = ..., result: _Optional[_Union[ExecResult, _Mapping]] = ...) -> None: ...

class InspectRequest(_message.Message):
    __slots__ = ("execution_id",)
    EXECUTION_ID_FIELD_NUMBER: _ClassVar[int]
    execution_id: str
    def __init__(self, execution_id: _Optional[str] = ...) -> None: ...

class InspectResponse(_message.Message):
    __slots__ = ("execution",)
    EXECUTION_FIELD_NUMBER: _ClassVar[int]
    execution: Execution
    def __init__(self, execution: _Optional[_Union[Execution, _Mapping]] = ...) -> None: ...

class ListRequest(_message.Message):
    __slots__ = ("labels",)
    class LabelsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    LABELS_FIELD_NUMBER: _ClassVar[int]
    labels: _containers.ScalarMap[str, str]
    def __init__(self, labels: _Optional[_Mapping[str, str]] = ...) -> None: ...

class ListResponse(_message.Message):
    __slots__ = ("executions",)
    EXECUTIONS_FIELD_NUMBER: _ClassVar[int]
    executions: _containers.RepeatedCompositeFieldContainer[Execution]
    def __init__(self, executions: _Optional[_Iterable[_Union[Execution, _Mapping]]] = ...) -> None: ...

class FileInfo(_message.Message):
    __slots__ = ("path", "name", "type", "size", "mode", "modified_at", "link_target")
    PATH_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    TYPE_FIELD_NUMBER: _ClassVar[int]
    SIZE_FIELD_NUMBER: _ClassVar[int]
    MODE_FIELD_NUMBER: _ClassVar[int]
    MODIFIED_AT_FIELD_NUMBER: _ClassVar[int]
    LINK_TARGET_FIELD_NUMBER: _ClassVar[int]
    path: str
    name: str
    type: FileType
    size: int
    mode: int
    modified_at: _timestamp_pb2.Timestamp
    link_target: str
    def __init__(self, path: _Optional[str] = ..., name: _Optional[str] = ..., type: _Optional[_Union[FileType, str]] = ..., size: _Optional[int] = ..., mode: _Optional[int] = ..., modified_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., link_target: _Optional[str] = ...) -> None: ...

class ReadFileRequest(_message.Message):
    __slots__ = ("session_id", "path", "offset", "length")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    OFFSET_FIELD_NUMBER: _ClassVar[int]
    LENGTH_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    path: str
    offset: int
    length: int
    def __init__(self, session_id: _Optional[str] = ..., path: _Optional[str] = ..., offset: _Optional[int] = ..., length: _Optional[int] = ...) -> None: ...

class ReadFileResponse(_message.Message):
    __slots__ = ("info", "data")
    INFO_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    info: FileInfo
    data: bytes
    def __init__(self, info: _Optional[_Union[FileInfo, _Mapping]] = ..., data: _Optional[bytes] = ...) -> None: ...

class WriteFileHeader(_message.Message):
    __slots__ = ("session_id", "path", "size", "sha256", "mode", "overwrite", "make_parents")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    SIZE_FIELD_NUMBER: _ClassVar[int]
    SHA256_FIELD_NUMBER: _ClassVar[int]
    MODE_FIELD_NUMBER: _ClassVar[int]
    OVERWRITE_FIELD_NUMBER: _ClassVar[int]
    MAKE_PARENTS_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    path: str
    size: int
    sha256: str
    mode: int
    overwrite: bool
    make_parents: bool
    def __init__(self, session_id: _Optional[str] = ..., path: _Optional[str] = ..., size: _Optional[int] = ..., sha256: _Optional[str] = ..., mode: _Optional[int] = ..., overwrite: bool = ..., make_parents: bool = ...) -> None: ...

class WriteFileRequest(_message.Message):
    __slots__ = ("header", "data")
    HEADER_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    header: WriteFileHeader
    data: bytes
    def __init__(self, header: _Optional[_Union[WriteFileHeader, _Mapping]] = ..., data: _Optional[bytes] = ...) -> None: ...

class WriteFileResponse(_message.Message):
    __slots__ = ("info", "sha256")
    INFO_FIELD_NUMBER: _ClassVar[int]
    SHA256_FIELD_NUMBER: _ClassVar[int]
    info: FileInfo
    sha256: str
    def __init__(self, info: _Optional[_Union[FileInfo, _Mapping]] = ..., sha256: _Optional[str] = ...) -> None: ...

class UploadFileHeader(_message.Message):
    __slots__ = ("session_id", "file_name", "size", "sha256", "directory")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    FILE_NAME_FIELD_NUMBER: _ClassVar[int]
    SIZE_FIELD_NUMBER: _ClassVar[int]
    SHA256_FIELD_NUMBER: _ClassVar[int]
    DIRECTORY_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    file_name: str
    size: int
    sha256: str
    directory: str
    def __init__(self, session_id: _Optional[str] = ..., file_name: _Optional[str] = ..., size: _Optional[int] = ..., sha256: _Optional[str] = ..., directory: _Optional[str] = ...) -> None: ...

class UploadFileRequest(_message.Message):
    __slots__ = ("header", "data")
    HEADER_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    header: UploadFileHeader
    data: bytes
    def __init__(self, header: _Optional[_Union[UploadFileHeader, _Mapping]] = ..., data: _Optional[bytes] = ...) -> None: ...

class UploadFileResponse(_message.Message):
    __slots__ = ("info", "sha256")
    INFO_FIELD_NUMBER: _ClassVar[int]
    SHA256_FIELD_NUMBER: _ClassVar[int]
    info: FileInfo
    sha256: str
    def __init__(self, info: _Optional[_Union[FileInfo, _Mapping]] = ..., sha256: _Optional[str] = ...) -> None: ...

class ListFilesRequest(_message.Message):
    __slots__ = ("session_id", "path", "recursive", "max_depth", "exclude_names", "skip_hidden", "max_entries")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    RECURSIVE_FIELD_NUMBER: _ClassVar[int]
    MAX_DEPTH_FIELD_NUMBER: _ClassVar[int]
    EXCLUDE_NAMES_FIELD_NUMBER: _ClassVar[int]
    SKIP_HIDDEN_FIELD_NUMBER: _ClassVar[int]
    MAX_ENTRIES_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    path: str
    recursive: bool
    max_depth: int
    exclude_names: _containers.RepeatedScalarFieldContainer[str]
    skip_hidden: bool
    max_entries: int
    def __init__(self, session_id: _Optional[str] = ..., path: _Optional[str] = ..., recursive: bool = ..., max_depth: _Optional[int] = ..., exclude_names: _Optional[_Iterable[str]] = ..., skip_hidden: bool = ..., max_entries: _Optional[int] = ...) -> None: ...

class ListFilesResponse(_message.Message):
    __slots__ = ("entries", "truncated")
    ENTRIES_FIELD_NUMBER: _ClassVar[int]
    TRUNCATED_FIELD_NUMBER: _ClassVar[int]
    entries: _containers.RepeatedCompositeFieldContainer[FileInfo]
    truncated: bool
    def __init__(self, entries: _Optional[_Iterable[_Union[FileInfo, _Mapping]]] = ..., truncated: bool = ...) -> None: ...

class DeleteFileRequest(_message.Message):
    __slots__ = ("session_id", "path", "recursive")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    RECURSIVE_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    path: str
    recursive: bool
    def __init__(self, session_id: _Optional[str] = ..., path: _Optional[str] = ..., recursive: bool = ...) -> None: ...

class DeleteFileResponse(_message.Message):
    __slots__ = ("deleted",)
    DELETED_FIELD_NUMBER: _ClassVar[int]
    deleted: bool
    def __init__(self, deleted: bool = ...) -> None: ...

class ZipFilesRequest(_message.Message):
    __slots__ = ("session_id", "path", "exclude_names", "skip_hidden")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    EXCLUDE_NAMES_FIELD_NUMBER: _ClassVar[int]
    SKIP_HIDDEN_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    path: str
    exclude_names: _containers.RepeatedScalarFieldContainer[str]
    skip_hidden: bool
    def __init__(self, session_id: _Optional[str] = ..., path: _Optional[str] = ..., exclude_names: _Optional[_Iterable[str]] = ..., skip_hidden: bool = ...) -> None: ...

class ZipSummary(_message.Message):
    __slots__ = ("files", "input_bytes", "zip_bytes", "skipped")
    FILES_FIELD_NUMBER: _ClassVar[int]
    INPUT_BYTES_FIELD_NUMBER: _ClassVar[int]
    ZIP_BYTES_FIELD_NUMBER: _ClassVar[int]
    SKIPPED_FIELD_NUMBER: _ClassVar[int]
    files: int
    input_bytes: int
    zip_bytes: int
    skipped: int
    def __init__(self, files: _Optional[int] = ..., input_bytes: _Optional[int] = ..., zip_bytes: _Optional[int] = ..., skipped: _Optional[int] = ...) -> None: ...

class ZipFilesResponse(_message.Message):
    __slots__ = ("data", "summary")
    DATA_FIELD_NUMBER: _ClassVar[int]
    SUMMARY_FIELD_NUMBER: _ClassVar[int]
    data: bytes
    summary: ZipSummary
    def __init__(self, data: _Optional[bytes] = ..., summary: _Optional[_Union[ZipSummary, _Mapping]] = ...) -> None: ...

class ArchiveLimits(_message.Message):
    __slots__ = ("max_stored_bytes", "max_expanded_bytes", "max_entries")
    MAX_STORED_BYTES_FIELD_NUMBER: _ClassVar[int]
    MAX_EXPANDED_BYTES_FIELD_NUMBER: _ClassVar[int]
    MAX_ENTRIES_FIELD_NUMBER: _ClassVar[int]
    max_stored_bytes: int
    max_expanded_bytes: int
    max_entries: int
    def __init__(self, max_stored_bytes: _Optional[int] = ..., max_expanded_bytes: _Optional[int] = ..., max_entries: _Optional[int] = ...) -> None: ...

class CaptureSessionRequest(_message.Message):
    __slots__ = ("session_id", "roots", "exclude_names", "limits")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    ROOTS_FIELD_NUMBER: _ClassVar[int]
    EXCLUDE_NAMES_FIELD_NUMBER: _ClassVar[int]
    LIMITS_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    roots: _containers.RepeatedScalarFieldContainer[str]
    exclude_names: _containers.RepeatedScalarFieldContainer[str]
    limits: ArchiveLimits
    def __init__(self, session_id: _Optional[str] = ..., roots: _Optional[_Iterable[str]] = ..., exclude_names: _Optional[_Iterable[str]] = ..., limits: _Optional[_Union[ArchiveLimits, _Mapping]] = ...) -> None: ...

class CaptureSummary(_message.Message):
    __slots__ = ("stored_bytes", "sha256", "files", "directories", "expanded_bytes", "excluded", "skipped", "changed", "roots")
    STORED_BYTES_FIELD_NUMBER: _ClassVar[int]
    SHA256_FIELD_NUMBER: _ClassVar[int]
    FILES_FIELD_NUMBER: _ClassVar[int]
    DIRECTORIES_FIELD_NUMBER: _ClassVar[int]
    EXPANDED_BYTES_FIELD_NUMBER: _ClassVar[int]
    EXCLUDED_FIELD_NUMBER: _ClassVar[int]
    SKIPPED_FIELD_NUMBER: _ClassVar[int]
    CHANGED_FIELD_NUMBER: _ClassVar[int]
    ROOTS_FIELD_NUMBER: _ClassVar[int]
    stored_bytes: int
    sha256: str
    files: int
    directories: int
    expanded_bytes: int
    excluded: int
    skipped: int
    changed: int
    roots: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, stored_bytes: _Optional[int] = ..., sha256: _Optional[str] = ..., files: _Optional[int] = ..., directories: _Optional[int] = ..., expanded_bytes: _Optional[int] = ..., excluded: _Optional[int] = ..., skipped: _Optional[int] = ..., changed: _Optional[int] = ..., roots: _Optional[_Iterable[str]] = ...) -> None: ...

class CaptureSessionResponse(_message.Message):
    __slots__ = ("data", "summary")
    DATA_FIELD_NUMBER: _ClassVar[int]
    SUMMARY_FIELD_NUMBER: _ClassVar[int]
    data: bytes
    summary: CaptureSummary
    def __init__(self, data: _Optional[bytes] = ..., summary: _Optional[_Union[CaptureSummary, _Mapping]] = ...) -> None: ...

class RestoreSessionHeader(_message.Message):
    __slots__ = ("session_id", "size_bytes", "sha256", "roots", "limits")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    SIZE_BYTES_FIELD_NUMBER: _ClassVar[int]
    SHA256_FIELD_NUMBER: _ClassVar[int]
    ROOTS_FIELD_NUMBER: _ClassVar[int]
    LIMITS_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    size_bytes: int
    sha256: str
    roots: _containers.RepeatedScalarFieldContainer[str]
    limits: ArchiveLimits
    def __init__(self, session_id: _Optional[str] = ..., size_bytes: _Optional[int] = ..., sha256: _Optional[str] = ..., roots: _Optional[_Iterable[str]] = ..., limits: _Optional[_Union[ArchiveLimits, _Mapping]] = ...) -> None: ...

class RestoreSessionRequest(_message.Message):
    __slots__ = ("header", "data")
    HEADER_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    header: RestoreSessionHeader
    data: bytes
    def __init__(self, header: _Optional[_Union[RestoreSessionHeader, _Mapping]] = ..., data: _Optional[bytes] = ...) -> None: ...

class RestoreSessionResponse(_message.Message):
    __slots__ = ("files", "directories", "expanded_bytes", "roots")
    FILES_FIELD_NUMBER: _ClassVar[int]
    DIRECTORIES_FIELD_NUMBER: _ClassVar[int]
    EXPANDED_BYTES_FIELD_NUMBER: _ClassVar[int]
    ROOTS_FIELD_NUMBER: _ClassVar[int]
    files: int
    directories: int
    expanded_bytes: int
    roots: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, files: _Optional[int] = ..., directories: _Optional[int] = ..., expanded_bytes: _Optional[int] = ..., roots: _Optional[_Iterable[str]] = ...) -> None: ...

class BrowserStartRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class BrowserStartResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class BrowserStopRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class BrowserStopResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ManagedStatusRequest(_message.Message):
    __slots__ = ("mount",)
    MOUNT_FIELD_NUMBER: _ClassVar[int]
    mount: str
    def __init__(self, mount: _Optional[str] = ...) -> None: ...

class ManagedSlotState(_message.Message):
    __slots__ = ("slot", "device", "present", "size_bytes", "fs_uuid", "mounted", "in_use")
    SLOT_FIELD_NUMBER: _ClassVar[int]
    DEVICE_FIELD_NUMBER: _ClassVar[int]
    PRESENT_FIELD_NUMBER: _ClassVar[int]
    SIZE_BYTES_FIELD_NUMBER: _ClassVar[int]
    FS_UUID_FIELD_NUMBER: _ClassVar[int]
    MOUNTED_FIELD_NUMBER: _ClassVar[int]
    IN_USE_FIELD_NUMBER: _ClassVar[int]
    slot: ManagedSlot
    device: str
    present: bool
    size_bytes: int
    fs_uuid: str
    mounted: bool
    in_use: bool
    def __init__(self, slot: _Optional[_Union[ManagedSlot, str]] = ..., device: _Optional[str] = ..., present: bool = ..., size_bytes: _Optional[int] = ..., fs_uuid: _Optional[str] = ..., mounted: bool = ..., in_use: bool = ...) -> None: ...

class ManagedStatusResponse(_message.Message):
    __slots__ = ("mount_point", "active", "slots", "mount")
    MOUNT_POINT_FIELD_NUMBER: _ClassVar[int]
    ACTIVE_FIELD_NUMBER: _ClassVar[int]
    SLOTS_FIELD_NUMBER: _ClassVar[int]
    MOUNT_FIELD_NUMBER: _ClassVar[int]
    mount_point: str
    active: ManagedSlot
    slots: _containers.RepeatedCompositeFieldContainer[ManagedSlotState]
    mount: str
    def __init__(self, mount_point: _Optional[str] = ..., active: _Optional[_Union[ManagedSlot, str]] = ..., slots: _Optional[_Iterable[_Union[ManagedSlotState, _Mapping]]] = ..., mount: _Optional[str] = ...) -> None: ...

class MountManagedRequest(_message.Message):
    __slots__ = ("slot", "mount", "size_bytes", "fs_uuid")
    SLOT_FIELD_NUMBER: _ClassVar[int]
    MOUNT_FIELD_NUMBER: _ClassVar[int]
    SIZE_BYTES_FIELD_NUMBER: _ClassVar[int]
    FS_UUID_FIELD_NUMBER: _ClassVar[int]
    slot: ManagedSlot
    mount: str
    size_bytes: int
    fs_uuid: str
    def __init__(self, slot: _Optional[_Union[ManagedSlot, str]] = ..., mount: _Optional[str] = ..., size_bytes: _Optional[int] = ..., fs_uuid: _Optional[str] = ...) -> None: ...

class MountManagedResponse(_message.Message):
    __slots__ = ("active", "changed", "previous", "previous_in_use", "wait_ms", "mount")
    ACTIVE_FIELD_NUMBER: _ClassVar[int]
    CHANGED_FIELD_NUMBER: _ClassVar[int]
    PREVIOUS_FIELD_NUMBER: _ClassVar[int]
    PREVIOUS_IN_USE_FIELD_NUMBER: _ClassVar[int]
    WAIT_MS_FIELD_NUMBER: _ClassVar[int]
    MOUNT_FIELD_NUMBER: _ClassVar[int]
    active: ManagedSlot
    changed: bool
    previous: ManagedSlot
    previous_in_use: bool
    wait_ms: int
    mount: str
    def __init__(self, active: _Optional[_Union[ManagedSlot, str]] = ..., changed: bool = ..., previous: _Optional[_Union[ManagedSlot, str]] = ..., previous_in_use: bool = ..., wait_ms: _Optional[int] = ..., mount: _Optional[str] = ...) -> None: ...
