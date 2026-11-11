# Generated from microvm/proto/hostagent/v1/hostagent.proto (blob d5b9138da2875146e2e720074770f287adc05128)
# at commit 461ea1e701 by backend/onyx/microvm/generated/regenerate.sh. Do not edit.
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
    MANAGED_IMAGE_MISSING: _ClassVar[ErrorReason]
    MANAGED_BUNDLE_INVALID: _ClassVar[ErrorReason]
    MANAGED_SWAP_UNSUPPORTED: _ClassVar[ErrorReason]
    MANAGED_SLOT_BUSY: _ClassVar[ErrorReason]
    MANAGED_MOUNT_FAILED: _ClassVar[ErrorReason]
    NODE_DRAINING: _ClassVar[ErrorReason]
    EGRESS_CA_UNAVAILABLE: _ClassVar[ErrorReason]
    CAPTURE_NOT_FOUND: _ClassVar[ErrorReason]
    CAPTURE_TOO_LARGE: _ClassVar[ErrorReason]
    TRANSFER_FAILED: _ClassVar[ErrorReason]
    ARCHIVE_MISMATCH: _ClassVar[ErrorReason]

class DrainState(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    DRAIN_STATE_UNSPECIFIED: _ClassVar[DrainState]
    DRAIN_STATE_ACTIVE: _ClassVar[DrainState]
    DRAIN_STATE_DRAINING: _ClassVar[DrainState]
    DRAIN_STATE_DRAINED: _ClassVar[DrainState]

class ManagedSlot(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    MANAGED_SLOT_UNSPECIFIED: _ClassVar[ManagedSlot]
    MANAGED_SLOT_A: _ClassVar[ManagedSlot]
    MANAGED_SLOT_B: _ClassVar[ManagedSlot]

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
MANAGED_IMAGE_MISSING: ErrorReason
MANAGED_BUNDLE_INVALID: ErrorReason
MANAGED_SWAP_UNSUPPORTED: ErrorReason
MANAGED_SLOT_BUSY: ErrorReason
MANAGED_MOUNT_FAILED: ErrorReason
NODE_DRAINING: ErrorReason
EGRESS_CA_UNAVAILABLE: ErrorReason
CAPTURE_NOT_FOUND: ErrorReason
CAPTURE_TOO_LARGE: ErrorReason
TRANSFER_FAILED: ErrorReason
ARCHIVE_MISMATCH: ErrorReason
DRAIN_STATE_UNSPECIFIED: DrainState
DRAIN_STATE_ACTIVE: DrainState
DRAIN_STATE_DRAINING: DrainState
DRAIN_STATE_DRAINED: DrainState
MANAGED_SLOT_UNSPECIFIED: ManagedSlot
MANAGED_SLOT_A: ManagedSlot
MANAGED_SLOT_B: ManagedSlot
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
    __slots__ = ("sandbox_id", "attempt", "generation", "template", "vcpus", "mem_mib", "scratch_gib", "state", "pid", "uid", "started_at", "tenant_id", "managed")
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
    MANAGED_FIELD_NUMBER: _ClassVar[int]
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
    managed: ManagedState
    def __init__(self, sandbox_id: _Optional[str] = ..., attempt: _Optional[int] = ..., generation: _Optional[int] = ..., template: _Optional[str] = ..., vcpus: _Optional[int] = ..., mem_mib: _Optional[int] = ..., scratch_gib: _Optional[int] = ..., state: _Optional[_Union[VMState, str]] = ..., pid: _Optional[int] = ..., uid: _Optional[int] = ..., started_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., tenant_id: _Optional[str] = ..., managed: _Optional[_Union[ManagedState, _Mapping]] = ...) -> None: ...

class ManagedState(_message.Message):
    __slots__ = ("slots", "active", "slot_a_image", "slot_b_image")
    SLOTS_FIELD_NUMBER: _ClassVar[int]
    ACTIVE_FIELD_NUMBER: _ClassVar[int]
    SLOT_A_IMAGE_FIELD_NUMBER: _ClassVar[int]
    SLOT_B_IMAGE_FIELD_NUMBER: _ClassVar[int]
    slots: int
    active: ManagedSlot
    slot_a_image: str
    slot_b_image: str
    def __init__(self, slots: _Optional[int] = ..., active: _Optional[_Union[ManagedSlot, str]] = ..., slot_a_image: _Optional[str] = ..., slot_b_image: _Optional[str] = ...) -> None: ...

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

class PresignedRequest(_message.Message):
    __slots__ = ("url", "method", "headers")
    class HeadersEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    URL_FIELD_NUMBER: _ClassVar[int]
    METHOD_FIELD_NUMBER: _ClassVar[int]
    HEADERS_FIELD_NUMBER: _ClassVar[int]
    url: str
    method: str
    headers: _containers.ScalarMap[str, str]
    def __init__(self, url: _Optional[str] = ..., method: _Optional[str] = ..., headers: _Optional[_Mapping[str, str]] = ...) -> None: ...

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
    __slots__ = ("sandbox_id", "attempt", "generation", "sandboxd_key", "session_id", "roots", "exclude_names", "limits")
    SANDBOX_ID_FIELD_NUMBER: _ClassVar[int]
    ATTEMPT_FIELD_NUMBER: _ClassVar[int]
    GENERATION_FIELD_NUMBER: _ClassVar[int]
    SANDBOXD_KEY_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    ROOTS_FIELD_NUMBER: _ClassVar[int]
    EXCLUDE_NAMES_FIELD_NUMBER: _ClassVar[int]
    LIMITS_FIELD_NUMBER: _ClassVar[int]
    sandbox_id: str
    attempt: int
    generation: int
    sandboxd_key: str
    session_id: str
    roots: _containers.RepeatedScalarFieldContainer[str]
    exclude_names: _containers.RepeatedScalarFieldContainer[str]
    limits: ArchiveLimits
    def __init__(self, sandbox_id: _Optional[str] = ..., attempt: _Optional[int] = ..., generation: _Optional[int] = ..., sandboxd_key: _Optional[str] = ..., session_id: _Optional[str] = ..., roots: _Optional[_Iterable[str]] = ..., exclude_names: _Optional[_Iterable[str]] = ..., limits: _Optional[_Union[ArchiveLimits, _Mapping]] = ...) -> None: ...

class CaptureSessionResponse(_message.Message):
    __slots__ = ("capture_id", "size_bytes", "sha256", "files", "directories", "expanded_bytes", "excluded", "skipped", "changed", "roots", "capture_ms", "expires_at")
    CAPTURE_ID_FIELD_NUMBER: _ClassVar[int]
    SIZE_BYTES_FIELD_NUMBER: _ClassVar[int]
    SHA256_FIELD_NUMBER: _ClassVar[int]
    FILES_FIELD_NUMBER: _ClassVar[int]
    DIRECTORIES_FIELD_NUMBER: _ClassVar[int]
    EXPANDED_BYTES_FIELD_NUMBER: _ClassVar[int]
    EXCLUDED_FIELD_NUMBER: _ClassVar[int]
    SKIPPED_FIELD_NUMBER: _ClassVar[int]
    CHANGED_FIELD_NUMBER: _ClassVar[int]
    ROOTS_FIELD_NUMBER: _ClassVar[int]
    CAPTURE_MS_FIELD_NUMBER: _ClassVar[int]
    EXPIRES_AT_FIELD_NUMBER: _ClassVar[int]
    capture_id: str
    size_bytes: int
    sha256: str
    files: int
    directories: int
    expanded_bytes: int
    excluded: int
    skipped: int
    changed: int
    roots: _containers.RepeatedScalarFieldContainer[str]
    capture_ms: int
    expires_at: _timestamp_pb2.Timestamp
    def __init__(self, capture_id: _Optional[str] = ..., size_bytes: _Optional[int] = ..., sha256: _Optional[str] = ..., files: _Optional[int] = ..., directories: _Optional[int] = ..., expanded_bytes: _Optional[int] = ..., excluded: _Optional[int] = ..., skipped: _Optional[int] = ..., changed: _Optional[int] = ..., roots: _Optional[_Iterable[str]] = ..., capture_ms: _Optional[int] = ..., expires_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class UploadCaptureRequest(_message.Message):
    __slots__ = ("capture_id", "request")
    CAPTURE_ID_FIELD_NUMBER: _ClassVar[int]
    REQUEST_FIELD_NUMBER: _ClassVar[int]
    capture_id: str
    request: PresignedRequest
    def __init__(self, capture_id: _Optional[str] = ..., request: _Optional[_Union[PresignedRequest, _Mapping]] = ...) -> None: ...

class UploadCaptureResponse(_message.Message):
    __slots__ = ("size_bytes", "sha256", "http_status", "etag", "upload_ms")
    SIZE_BYTES_FIELD_NUMBER: _ClassVar[int]
    SHA256_FIELD_NUMBER: _ClassVar[int]
    HTTP_STATUS_FIELD_NUMBER: _ClassVar[int]
    ETAG_FIELD_NUMBER: _ClassVar[int]
    UPLOAD_MS_FIELD_NUMBER: _ClassVar[int]
    size_bytes: int
    sha256: str
    http_status: int
    etag: str
    upload_ms: int
    def __init__(self, size_bytes: _Optional[int] = ..., sha256: _Optional[str] = ..., http_status: _Optional[int] = ..., etag: _Optional[str] = ..., upload_ms: _Optional[int] = ...) -> None: ...

class DiscardCaptureRequest(_message.Message):
    __slots__ = ("capture_id",)
    CAPTURE_ID_FIELD_NUMBER: _ClassVar[int]
    capture_id: str
    def __init__(self, capture_id: _Optional[str] = ...) -> None: ...

class DiscardCaptureResponse(_message.Message):
    __slots__ = ("discarded",)
    DISCARDED_FIELD_NUMBER: _ClassVar[int]
    discarded: bool
    def __init__(self, discarded: bool = ...) -> None: ...

class RestoreSessionRequest(_message.Message):
    __slots__ = ("sandbox_id", "attempt", "generation", "sandboxd_key", "session_id", "request", "size_bytes", "sha256", "roots", "limits")
    SANDBOX_ID_FIELD_NUMBER: _ClassVar[int]
    ATTEMPT_FIELD_NUMBER: _ClassVar[int]
    GENERATION_FIELD_NUMBER: _ClassVar[int]
    SANDBOXD_KEY_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    REQUEST_FIELD_NUMBER: _ClassVar[int]
    SIZE_BYTES_FIELD_NUMBER: _ClassVar[int]
    SHA256_FIELD_NUMBER: _ClassVar[int]
    ROOTS_FIELD_NUMBER: _ClassVar[int]
    LIMITS_FIELD_NUMBER: _ClassVar[int]
    sandbox_id: str
    attempt: int
    generation: int
    sandboxd_key: str
    session_id: str
    request: PresignedRequest
    size_bytes: int
    sha256: str
    roots: _containers.RepeatedScalarFieldContainer[str]
    limits: ArchiveLimits
    def __init__(self, sandbox_id: _Optional[str] = ..., attempt: _Optional[int] = ..., generation: _Optional[int] = ..., sandboxd_key: _Optional[str] = ..., session_id: _Optional[str] = ..., request: _Optional[_Union[PresignedRequest, _Mapping]] = ..., size_bytes: _Optional[int] = ..., sha256: _Optional[str] = ..., roots: _Optional[_Iterable[str]] = ..., limits: _Optional[_Union[ArchiveLimits, _Mapping]] = ...) -> None: ...

class RestoreSessionResponse(_message.Message):
    __slots__ = ("files", "directories", "expanded_bytes", "roots", "restore_ms")
    FILES_FIELD_NUMBER: _ClassVar[int]
    DIRECTORIES_FIELD_NUMBER: _ClassVar[int]
    EXPANDED_BYTES_FIELD_NUMBER: _ClassVar[int]
    ROOTS_FIELD_NUMBER: _ClassVar[int]
    RESTORE_MS_FIELD_NUMBER: _ClassVar[int]
    files: int
    directories: int
    expanded_bytes: int
    roots: _containers.RepeatedScalarFieldContainer[str]
    restore_ms: int
    def __init__(self, files: _Optional[int] = ..., directories: _Optional[int] = ..., expanded_bytes: _Optional[int] = ..., roots: _Optional[_Iterable[str]] = ..., restore_ms: _Optional[int] = ...) -> None: ...

class NodeInfoRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class NodeInfoResponse(_message.Message):
    __slots__ = ("mem_total_mib", "mem_available_mib", "vm_count", "templates", "cpu_model", "firecracker_version", "host_kernel", "agent_version", "disk_free_mib", "managed_images", "mem_reserve_mib", "mem_starting_mib", "drain")
    MEM_TOTAL_MIB_FIELD_NUMBER: _ClassVar[int]
    MEM_AVAILABLE_MIB_FIELD_NUMBER: _ClassVar[int]
    VM_COUNT_FIELD_NUMBER: _ClassVar[int]
    TEMPLATES_FIELD_NUMBER: _ClassVar[int]
    CPU_MODEL_FIELD_NUMBER: _ClassVar[int]
    FIRECRACKER_VERSION_FIELD_NUMBER: _ClassVar[int]
    HOST_KERNEL_FIELD_NUMBER: _ClassVar[int]
    AGENT_VERSION_FIELD_NUMBER: _ClassVar[int]
    DISK_FREE_MIB_FIELD_NUMBER: _ClassVar[int]
    MANAGED_IMAGES_FIELD_NUMBER: _ClassVar[int]
    MEM_RESERVE_MIB_FIELD_NUMBER: _ClassVar[int]
    MEM_STARTING_MIB_FIELD_NUMBER: _ClassVar[int]
    DRAIN_FIELD_NUMBER: _ClassVar[int]
    mem_total_mib: int
    mem_available_mib: int
    vm_count: int
    templates: _containers.RepeatedCompositeFieldContainer[TemplateInfo]
    cpu_model: str
    firecracker_version: str
    host_kernel: str
    agent_version: str
    disk_free_mib: int
    managed_images: _containers.RepeatedCompositeFieldContainer[ManagedImageInfo]
    mem_reserve_mib: int
    mem_starting_mib: int
    drain: DrainStatus
    def __init__(self, mem_total_mib: _Optional[int] = ..., mem_available_mib: _Optional[int] = ..., vm_count: _Optional[int] = ..., templates: _Optional[_Iterable[_Union[TemplateInfo, _Mapping]]] = ..., cpu_model: _Optional[str] = ..., firecracker_version: _Optional[str] = ..., host_kernel: _Optional[str] = ..., agent_version: _Optional[str] = ..., disk_free_mib: _Optional[int] = ..., managed_images: _Optional[_Iterable[_Union[ManagedImageInfo, _Mapping]]] = ..., mem_reserve_mib: _Optional[int] = ..., mem_starting_mib: _Optional[int] = ..., drain: _Optional[_Union[DrainStatus, _Mapping]] = ...) -> None: ...

class DrainStatus(_message.Message):
    __slots__ = ("state", "manual", "taints", "since", "watch_error")
    STATE_FIELD_NUMBER: _ClassVar[int]
    MANUAL_FIELD_NUMBER: _ClassVar[int]
    TAINTS_FIELD_NUMBER: _ClassVar[int]
    SINCE_FIELD_NUMBER: _ClassVar[int]
    WATCH_ERROR_FIELD_NUMBER: _ClassVar[int]
    state: DrainState
    manual: bool
    taints: _containers.RepeatedScalarFieldContainer[str]
    since: _timestamp_pb2.Timestamp
    watch_error: str
    def __init__(self, state: _Optional[_Union[DrainState, str]] = ..., manual: bool = ..., taints: _Optional[_Iterable[str]] = ..., since: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., watch_error: _Optional[str] = ...) -> None: ...

class SetDrainRequest(_message.Message):
    __slots__ = ("drain",)
    DRAIN_FIELD_NUMBER: _ClassVar[int]
    drain: bool
    def __init__(self, drain: bool = ...) -> None: ...

class SetDrainResponse(_message.Message):
    __slots__ = ("drain",)
    DRAIN_FIELD_NUMBER: _ClassVar[int]
    drain: DrainStatus
    def __init__(self, drain: _Optional[_Union[DrainStatus, _Mapping]] = ...) -> None: ...

class TemplateInfo(_message.Message):
    __slots__ = ("version", "vcpus", "mem_mib", "scratch_gib", "guest_kernel", "firecracker_version", "image_ref", "image_digest", "rootfs_sha256", "key_sha256", "ca_fingerprint", "built_at", "compatible", "managed_slots", "balloon")
    VERSION_FIELD_NUMBER: _ClassVar[int]
    VCPUS_FIELD_NUMBER: _ClassVar[int]
    MEM_MIB_FIELD_NUMBER: _ClassVar[int]
    SCRATCH_GIB_FIELD_NUMBER: _ClassVar[int]
    GUEST_KERNEL_FIELD_NUMBER: _ClassVar[int]
    FIRECRACKER_VERSION_FIELD_NUMBER: _ClassVar[int]
    IMAGE_REF_FIELD_NUMBER: _ClassVar[int]
    IMAGE_DIGEST_FIELD_NUMBER: _ClassVar[int]
    ROOTFS_SHA256_FIELD_NUMBER: _ClassVar[int]
    KEY_SHA256_FIELD_NUMBER: _ClassVar[int]
    CA_FINGERPRINT_FIELD_NUMBER: _ClassVar[int]
    BUILT_AT_FIELD_NUMBER: _ClassVar[int]
    COMPATIBLE_FIELD_NUMBER: _ClassVar[int]
    MANAGED_SLOTS_FIELD_NUMBER: _ClassVar[int]
    BALLOON_FIELD_NUMBER: _ClassVar[int]
    version: str
    vcpus: int
    mem_mib: int
    scratch_gib: int
    guest_kernel: str
    firecracker_version: str
    image_ref: str
    image_digest: str
    rootfs_sha256: str
    key_sha256: str
    ca_fingerprint: str
    built_at: _timestamp_pb2.Timestamp
    compatible: bool
    managed_slots: int
    balloon: bool
    def __init__(self, version: _Optional[str] = ..., vcpus: _Optional[int] = ..., mem_mib: _Optional[int] = ..., scratch_gib: _Optional[int] = ..., guest_kernel: _Optional[str] = ..., firecracker_version: _Optional[str] = ..., image_ref: _Optional[str] = ..., image_digest: _Optional[str] = ..., rootfs_sha256: _Optional[str] = ..., key_sha256: _Optional[str] = ..., ca_fingerprint: _Optional[str] = ..., built_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., compatible: bool = ..., managed_slots: _Optional[int] = ..., balloon: bool = ...) -> None: ...

class BuildTemplateRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class BuildTemplateResponse(_message.Message):
    __slots__ = ("template", "built", "build_ms", "removed")
    TEMPLATE_FIELD_NUMBER: _ClassVar[int]
    BUILT_FIELD_NUMBER: _ClassVar[int]
    BUILD_MS_FIELD_NUMBER: _ClassVar[int]
    REMOVED_FIELD_NUMBER: _ClassVar[int]
    template: TemplateInfo
    built: bool
    build_ms: int
    removed: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, template: _Optional[_Union[TemplateInfo, _Mapping]] = ..., built: bool = ..., build_ms: _Optional[int] = ..., removed: _Optional[_Iterable[str]] = ...) -> None: ...

class PutManagedImageRequest(_message.Message):
    __slots__ = ("header", "data")
    HEADER_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    header: ManagedBundleHeader
    data: bytes
    def __init__(self, header: _Optional[_Union[ManagedBundleHeader, _Mapping]] = ..., data: _Optional[bytes] = ...) -> None: ...

class ManagedBundleHeader(_message.Message):
    __slots__ = ("sha256", "size_bytes")
    SHA256_FIELD_NUMBER: _ClassVar[int]
    SIZE_BYTES_FIELD_NUMBER: _ClassVar[int]
    sha256: str
    size_bytes: int
    def __init__(self, sha256: _Optional[str] = ..., size_bytes: _Optional[int] = ...) -> None: ...

class PutManagedImageResponse(_message.Message):
    __slots__ = ("image", "built", "build_ms", "removed")
    IMAGE_FIELD_NUMBER: _ClassVar[int]
    BUILT_FIELD_NUMBER: _ClassVar[int]
    BUILD_MS_FIELD_NUMBER: _ClassVar[int]
    REMOVED_FIELD_NUMBER: _ClassVar[int]
    image: ManagedImageInfo
    built: bool
    build_ms: int
    removed: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, image: _Optional[_Union[ManagedImageInfo, _Mapping]] = ..., built: bool = ..., build_ms: _Optional[int] = ..., removed: _Optional[_Iterable[str]] = ...) -> None: ...

class ManagedImageInfo(_message.Message):
    __slots__ = ("image_id", "image_sha256", "size_bytes", "fs_uuid", "files", "content_bytes", "built_at", "vms")
    IMAGE_ID_FIELD_NUMBER: _ClassVar[int]
    IMAGE_SHA256_FIELD_NUMBER: _ClassVar[int]
    SIZE_BYTES_FIELD_NUMBER: _ClassVar[int]
    FS_UUID_FIELD_NUMBER: _ClassVar[int]
    FILES_FIELD_NUMBER: _ClassVar[int]
    CONTENT_BYTES_FIELD_NUMBER: _ClassVar[int]
    BUILT_AT_FIELD_NUMBER: _ClassVar[int]
    VMS_FIELD_NUMBER: _ClassVar[int]
    image_id: str
    image_sha256: str
    size_bytes: int
    fs_uuid: str
    files: int
    content_bytes: int
    built_at: _timestamp_pb2.Timestamp
    vms: int
    def __init__(self, image_id: _Optional[str] = ..., image_sha256: _Optional[str] = ..., size_bytes: _Optional[int] = ..., fs_uuid: _Optional[str] = ..., files: _Optional[int] = ..., content_bytes: _Optional[int] = ..., built_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., vms: _Optional[int] = ...) -> None: ...

class SwapManagedRequest(_message.Message):
    __slots__ = ("image_id", "targets")
    IMAGE_ID_FIELD_NUMBER: _ClassVar[int]
    TARGETS_FIELD_NUMBER: _ClassVar[int]
    image_id: str
    targets: _containers.RepeatedCompositeFieldContainer[SwapTarget]
    def __init__(self, image_id: _Optional[str] = ..., targets: _Optional[_Iterable[_Union[SwapTarget, _Mapping]]] = ...) -> None: ...

class SwapTarget(_message.Message):
    __slots__ = ("sandbox_id", "attempt", "generation", "sandboxd_key")
    SANDBOX_ID_FIELD_NUMBER: _ClassVar[int]
    ATTEMPT_FIELD_NUMBER: _ClassVar[int]
    GENERATION_FIELD_NUMBER: _ClassVar[int]
    SANDBOXD_KEY_FIELD_NUMBER: _ClassVar[int]
    sandbox_id: str
    attempt: int
    generation: int
    sandboxd_key: str
    def __init__(self, sandbox_id: _Optional[str] = ..., attempt: _Optional[int] = ..., generation: _Optional[int] = ..., sandboxd_key: _Optional[str] = ...) -> None: ...

class SwapManagedResponse(_message.Message):
    __slots__ = ("results",)
    RESULTS_FIELD_NUMBER: _ClassVar[int]
    results: _containers.RepeatedCompositeFieldContainer[SwapResult]
    def __init__(self, results: _Optional[_Iterable[_Union[SwapResult, _Mapping]]] = ...) -> None: ...

class SwapResult(_message.Message):
    __slots__ = ("sandbox_id", "ok", "reason", "message", "active", "changed", "ms", "previous_in_use")
    SANDBOX_ID_FIELD_NUMBER: _ClassVar[int]
    OK_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    ACTIVE_FIELD_NUMBER: _ClassVar[int]
    CHANGED_FIELD_NUMBER: _ClassVar[int]
    MS_FIELD_NUMBER: _ClassVar[int]
    PREVIOUS_IN_USE_FIELD_NUMBER: _ClassVar[int]
    sandbox_id: str
    ok: bool
    reason: ErrorReason
    message: str
    active: ManagedSlot
    changed: bool
    ms: int
    previous_in_use: bool
    def __init__(self, sandbox_id: _Optional[str] = ..., ok: bool = ..., reason: _Optional[_Union[ErrorReason, str]] = ..., message: _Optional[str] = ..., active: _Optional[_Union[ManagedSlot, str]] = ..., changed: bool = ..., ms: _Optional[int] = ..., previous_in_use: bool = ...) -> None: ...
