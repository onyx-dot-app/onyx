from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from onyx.server.features.build.sandbox.models import (
    FileSet,
    HarnessSandboxRef,
)
from onyx.skills import push
from onyx.skills.models import ChatSkill
from onyx.tools.tool_implementations.sandbox import turn as turn_module
from onyx.tools.tool_implementations.sandbox.turn import SandboxTurn


class _RecordingSandbox:
    def __init__(self) -> None:
        self.versions: list[dict[str, str]] = []

    def install_skills(
        self,
        ref: HarnessSandboxRef,  # noqa: ARG002
        versions: Mapping[str, str],
        load: Callable[[str], FileSet | None],  # noqa: ARG002
    ) -> None:
        self.versions.append(dict(versions))


def test_a_new_read_of_a_skill_copies_its_current_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    v1 = ChatSkill(name="report", description="Report", version_id=uuid4())
    v2 = v1.model_copy(update={"version_id": uuid4()})
    current = [v1]
    lookups: list[int] = []

    @contextmanager
    def no_db(**_kwargs: object) -> Iterator[None]:
        yield None

    def list_chat_skills(*_args: object, **_kwargs: object) -> list[ChatSkill]:
        lookups.append(1)
        return list(current)

    sandbox = _RecordingSandbox()
    monkeypatch.setattr(turn_module, "get_session_with_tenant", no_db)
    monkeypatch.setattr(turn_module, "list_chat_skills", list_chat_skills)
    monkeypatch.setattr(SandboxTurn, "sandbox", property(lambda _: sandbox))
    turn = SandboxTurn(
        tenant_id="t",
        user=MagicMock(id=uuid4()),
        chat_session_id=uuid4(),
        vm_chat_files=[],
        copy_vm_chat_files=False,
    )
    ref = HarnessSandboxRef(tenant_id="t", sandbox_id=uuid4(), session_id=uuid4())

    turn.want_skills({"report": 1})
    turn._install_custom_skills(ref)
    current[:] = [v2]
    turn.want_skills({"report": 1})
    turn._install_custom_skills(ref)
    turn.want_skills({"report": 2})
    turn._install_custom_skills(ref)

    assert [v["report"].split(":")[0] for v in sandbox.versions] == [
        str(v1.version_id),
        str(v1.version_id),
        str(v2.version_id),
    ]
    assert len(lookups) == 2


def test_a_read_during_the_skill_lookup_takes_effect_on_the_next_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    v1 = ChatSkill(name="report", description="Report", version_id=uuid4())
    v2 = v1.model_copy(update={"version_id": uuid4()})
    current = [v1]
    turn: SandboxTurn

    @contextmanager
    def no_db(**_kwargs: object) -> Iterator[None]:
        yield None

    def list_chat_skills(*_args: object, **_kwargs: object) -> list[ChatSkill]:
        found = list(current)
        if found == [v1]:
            current[:] = [v2]
            turn.want_skills({"report": 2})
        return found

    sandbox = _RecordingSandbox()
    monkeypatch.setattr(turn_module, "get_session_with_tenant", no_db)
    monkeypatch.setattr(turn_module, "list_chat_skills", list_chat_skills)
    monkeypatch.setattr(SandboxTurn, "sandbox", property(lambda _: sandbox))
    turn = SandboxTurn(
        tenant_id="t",
        user=MagicMock(id=uuid4()),
        chat_session_id=uuid4(),
        vm_chat_files=[],
        copy_vm_chat_files=False,
    )
    ref = HarnessSandboxRef(tenant_id="t", sandbox_id=uuid4(), session_id=uuid4())

    turn.want_skills({"report": 1})
    turn._install_custom_skills(ref)
    turn._install_custom_skills(ref)

    assert [v["report"].split(":")[0] for v in sandbox.versions] == [
        str(v1.version_id),
        str(v2.version_id),
    ]


def test_a_failed_load_is_tried_again_on_the_next_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill = ChatSkill(name="report", description="Report", version_id=uuid4())
    builds: list[FileSet | None] = [None, {"report/SKILL.md": b"# report"}]
    loaded: list[FileSet | None] = []

    @contextmanager
    def no_db(**_kwargs: object) -> Iterator[None]:
        yield None

    class LoadingSandbox(_RecordingSandbox):
        def install_skills(
            self,
            ref: HarnessSandboxRef,
            versions: Mapping[str, str],
            load: Callable[[str], FileSet | None],
        ) -> None:
            super().install_skills(ref, versions, load)
            loaded.append(load("report"))

    sandbox = LoadingSandbox()
    monkeypatch.setattr(turn_module, "get_session_with_tenant", no_db)
    monkeypatch.setattr(turn_module, "list_chat_skills", lambda *_a, **_k: [skill])
    monkeypatch.setattr(
        push, "build_chat_custom_skill_files", lambda *_a, **_k: builds.pop(0)
    )
    monkeypatch.setattr(SandboxTurn, "sandbox", property(lambda _: sandbox))
    turn = SandboxTurn(
        tenant_id="t",
        user=MagicMock(id=uuid4()),
        chat_session_id=uuid4(),
        vm_chat_files=[],
        copy_vm_chat_files=False,
    )
    ref = HarnessSandboxRef(tenant_id="t", sandbox_id=uuid4(), session_id=uuid4())

    turn.want_skills({"report": 1})
    turn._install_custom_skills(ref)
    turn._install_custom_skills(ref)
    turn._install_custom_skills(ref)

    files = {"report/SKILL.md": b"# report"}
    assert loaded == [None, files, files]
