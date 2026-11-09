# Generated from microvm/proto/hostagent/v1/hostagent.proto (blob 141d38cc444960eaf251a9542a2d1d963e990389)
# at commit 46d3937602 by backend/onyx/microvm/generated/regenerate.sh. Do not edit.
import datetime

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
    TEMPLATE_MISSING: _ClassVar[ErrorReason]
    TEMPLATE_SHAPE_MISMATCH: _ClassVar[ErrorReason]
    TEMPLATE_INCOMPATIBLE: _ClassVar[ErrorReason]
    SCRATCH_TOO_SMALL: _ClassVar[ErrorReason]
    SCRATCH_TOO_LARGE: _ClassVar[ErrorReason]
    CAPACITY_MEMORY: _ClassVar[ErrorReason]
    CAPACITY_DISK: _ClassVar[ErrorReason]
    CAPACITY_VM_SLOTS: _ClassVar[ErrorReason]
    ATTEMPT_CONFLICT: _ClassVar[ErrorReason]
    STALE_ATTEMPT: _ClassVar[ErrorReason]
    SANDBOX_NOT_FOUND: _ClassVar[ErrorReason]
    INSTANCE_MISMATCH: _ClassVar[ErrorReason]
    VMM_FAILED: _ClassVar[ErrorReason]
    INTERNAL: _ClassVar[ErrorReason]
    SANDBOX_IN_DOUBT: _ClassVar[ErrorReason]
    PORT_NOT_ALLOWED: _ClassVar[ErrorReason]
    GUEST_UNREACHABLE: _ClassVar[ErrorReason]
    VM_NOT_RUNNING: _ClassVar[ErrorReason]
    DIAL_LIMIT: _ClassVar[ErrorReason]
    METHOD_NOT_ALLOWED: _ClassVar[ErrorReason]
    GUEST_KEY_REJECTED: _ClassVar[ErrorReason]

class VMState(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    VM_STATE_UNSPECIFIED: _ClassVar[VMState]
    VM_STATE_STARTING: _ClassVar[VMState]
    VM_STATE_RUNNING: _ClassVar[VMState]
    VM_STATE_EXITED: _ClassVar[VMState]
ERROR_REASON_UNSPECIFIED: ErrorReason
INVALID_ARGUMENT: ErrorReason
TEMPLATE_MISSING: ErrorReason
TEMPLATE_SHAPE_MISMATCH: ErrorReason
TEMPLATE_INCOMPATIBLE: ErrorReason
SCRATCH_TOO_SMALL: ErrorReason
SCRATCH_TOO_LARGE: ErrorReason
CAPACITY_MEMORY: ErrorReason
CAPACITY_DISK: ErrorReason
CAPACITY_VM_SLOTS: ErrorReason
ATTEMPT_CONFLICT: ErrorReason
STALE_ATTEMPT: ErrorReason
SANDBOX_NOT_FOUND: ErrorReason
INSTANCE_MISMATCH: ErrorReason
VMM_FAILED: ErrorReason
INTERNAL: ErrorReason
SANDBOX_IN_DOUBT: ErrorReason
PORT_NOT_ALLOWED: ErrorReason
GUEST_UNREACHABLE: ErrorReason
VM_NOT_RUNNING: ErrorReason
DIAL_LIMIT: ErrorReason
METHOD_NOT_ALLOWED: ErrorReason
GUEST_KEY_REJECTED: ErrorReason
VM_STATE_UNSPECIFIED: VMState
VM_STATE_STARTING: VMState
VM_STATE_RUNNING: VMState
VM_STATE_EXITED: VMState

class CreateRequest(_message.Message):
    __slots__ = ("sandbox_id", "attempt", "template", "vcpus", "mem_mib", "scratch_gib", "tenant_id", "sandboxd_key")
    SANDBOX_ID_FIELD_NUMBER: _ClassVar[int]
    ATTEMPT_FIELD_NUMBER: _ClassVar[int]
    TEMPLATE_FIELD_NUMBER: _ClassVar[int]
    VCPUS_FIELD_NUMBER: _ClassVar[int]
    MEM_MIB_FIELD_NUMBER: _ClassVar[int]
    SCRATCH_GIB_FIELD_NUMBER: _ClassVar[int]
    TENANT_ID_FIELD_NUMBER: _ClassVar[int]
    SANDBOXD_KEY_FIELD_NUMBER: _ClassVar[int]
    sandbox_id: str
    attempt: int
    template: str
    vcpus: int
    mem_mib: int
    scratch_gib: int
    tenant_id: str
    sandboxd_key: str
    def __init__(self, sandbox_id: _Optional[str] = ..., attempt: _Optional[int] = ..., template: _Optional[str] = ..., vcpus: _Optional[int] = ..., mem_mib: _Optional[int] = ..., scratch_gib: _Optional[int] = ..., tenant_id: _Optional[str] = ..., sandboxd_key: _Optional[str] = ...) -> None: ...

class CreateResponse(_message.Message):
    __slots__ = ("vm", "created")
    VM_FIELD_NUMBER: _ClassVar[int]
    CREATED_FIELD_NUMBER: _ClassVar[int]
    vm: VM
    created: bool
    def __init__(self, vm: _Optional[_Union[VM, _Mapping]] = ..., created: bool = ...) -> None: ...

class StopRequest(_message.Message):
    __slots__ = ("sandbox_id", "attempt", "generation")
    SANDBOX_ID_FIELD_NUMBER: _ClassVar[int]
    ATTEMPT_FIELD_NUMBER: _ClassVar[int]
    GENERATION_FIELD_NUMBER: _ClassVar[int]
    sandbox_id: str
    attempt: int
    generation: int
    def __init__(self, sandbox_id: _Optional[str] = ..., attempt: _Optional[int] = ..., generation: _Optional[int] = ...) -> None: ...

class StopResponse(_message.Message):
    __slots__ = ("already_stopped",)
    ALREADY_STOPPED_FIELD_NUMBER: _ClassVar[int]
    already_stopped: bool
    def __init__(self, already_stopped: bool = ...) -> None: ...

class ListRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ListResponse(_message.Message):
    __slots__ = ("vms",)
    VMS_FIELD_NUMBER: _ClassVar[int]
    vms: _containers.RepeatedCompositeFieldContainer[VM]
    def __init__(self, vms: _Optional[_Iterable[_Union[VM, _Mapping]]] = ...) -> None: ...

class VM(_message.Message):
    __slots__ = ("sandbox_id", "attempt", "generation", "template", "vcpus", "mem_mib", "scratch_gib", "state", "pid", "uid", "started_at", "tenant_id")
    SANDBOX_ID_FIELD_NUMBER: _ClassVar[int]
    ATTEMPT_FIELD_NUMBER: _ClassVar[int]
    GENERATION_FIELD_NUMBER: _ClassVar[int]
    TEMPLATE_FIELD_NUMBER: _ClassVar[int]
    VCPUS_FIELD_NUMBER: _ClassVar[int]
    MEM_MIB_FIELD_NUMBER: _ClassVar[int]
    SCRATCH_GIB_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    PID_FIELD_NUMBER: _ClassVar[int]
    UID_FIELD_NUMBER: _ClassVar[int]
    STARTED_AT_FIELD_NUMBER: _ClassVar[int]
    TENANT_ID_FIELD_NUMBER: _ClassVar[int]
    sandbox_id: str
    attempt: int
    generation: int
    template: str
    vcpus: int
    mem_mib: int
    scratch_gib: int
    state: VMState
    pid: int
    uid: int
    started_at: _timestamp_pb2.Timestamp
    tenant_id: str
    def __init__(self, sandbox_id: _Optional[str] = ..., attempt: _Optional[int] = ..., generation: _Optional[int] = ..., template: _Optional[str] = ..., vcpus: _Optional[int] = ..., mem_mib: _Optional[int] = ..., scratch_gib: _Optional[int] = ..., state: _Optional[_Union[VMState, str]] = ..., pid: _Optional[int] = ..., uid: _Optional[int] = ..., started_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., tenant_id: _Optional[str] = ...) -> None: ...

class CloseConnectionsRequest(_message.Message):
    __slots__ = ("sandbox_id", "attempt", "generation")
    SANDBOX_ID_FIELD_NUMBER: _ClassVar[int]
    ATTEMPT_FIELD_NUMBER: _ClassVar[int]
    GENERATION_FIELD_NUMBER: _ClassVar[int]
    sandbox_id: str
    attempt: int
    generation: int
    def __init__(self, sandbox_id: _Optional[str] = ..., attempt: _Optional[int] = ..., generation: _Optional[int] = ...) -> None: ...

class DialFrame(_message.Message):
    __slots__ = ("sandbox_id", "guest_port", "data", "generation")
    SANDBOX_ID_FIELD_NUMBER: _ClassVar[int]
    GUEST_PORT_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    GENERATION_FIELD_NUMBER: _ClassVar[int]
    sandbox_id: str
    guest_port: int
    data: bytes
    generation: int
    def __init__(self, sandbox_id: _Optional[str] = ..., guest_port: _Optional[int] = ..., data: _Optional[bytes] = ..., generation: _Optional[int] = ...) -> None: ...

class CloseConnectionsResponse(_message.Message):
    __slots__ = ("closed",)
    CLOSED_FIELD_NUMBER: _ClassVar[int]
    closed: int
    def __init__(self, closed: _Optional[int] = ...) -> None: ...

class NodeInfoRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class NodeInfoResponse(_message.Message):
    __slots__ = ("mem_total_mib", "mem_available_mib", "vm_count", "templates", "cpu_model", "firecracker_version", "host_kernel", "agent_version", "disk_free_mib")
    MEM_TOTAL_MIB_FIELD_NUMBER: _ClassVar[int]
    MEM_AVAILABLE_MIB_FIELD_NUMBER: _ClassVar[int]
    VM_COUNT_FIELD_NUMBER: _ClassVar[int]
    TEMPLATES_FIELD_NUMBER: _ClassVar[int]
    CPU_MODEL_FIELD_NUMBER: _ClassVar[int]
    FIRECRACKER_VERSION_FIELD_NUMBER: _ClassVar[int]
    HOST_KERNEL_FIELD_NUMBER: _ClassVar[int]
    AGENT_VERSION_FIELD_NUMBER: _ClassVar[int]
    DISK_FREE_MIB_FIELD_NUMBER: _ClassVar[int]
    mem_total_mib: int
    mem_available_mib: int
    vm_count: int
    templates: _containers.RepeatedCompositeFieldContainer[TemplateInfo]
    cpu_model: str
    firecracker_version: str
    host_kernel: str
    agent_version: str
    disk_free_mib: int
    def __init__(self, mem_total_mib: _Optional[int] = ..., mem_available_mib: _Optional[int] = ..., vm_count: _Optional[int] = ..., templates: _Optional[_Iterable[_Union[TemplateInfo, _Mapping]]] = ..., cpu_model: _Optional[str] = ..., firecracker_version: _Optional[str] = ..., host_kernel: _Optional[str] = ..., agent_version: _Optional[str] = ..., disk_free_mib: _Optional[int] = ...) -> None: ...

class TemplateInfo(_message.Message):
    __slots__ = ("version", "vcpus", "mem_mib", "scratch_gib", "guest_kernel", "firecracker_version")
    VERSION_FIELD_NUMBER: _ClassVar[int]
    VCPUS_FIELD_NUMBER: _ClassVar[int]
    MEM_MIB_FIELD_NUMBER: _ClassVar[int]
    SCRATCH_GIB_FIELD_NUMBER: _ClassVar[int]
    GUEST_KERNEL_FIELD_NUMBER: _ClassVar[int]
    FIRECRACKER_VERSION_FIELD_NUMBER: _ClassVar[int]
    version: str
    vcpus: int
    mem_mib: int
    scratch_gib: int
    guest_kernel: str
    firecracker_version: str
    def __init__(self, version: _Optional[str] = ..., vcpus: _Optional[int] = ..., mem_mib: _Optional[int] = ..., scratch_gib: _Optional[int] = ..., guest_kernel: _Optional[str] = ..., firecracker_version: _Optional[str] = ...) -> None: ...
