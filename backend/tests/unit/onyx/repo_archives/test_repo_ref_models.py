"""RepoRef's identity invariants: `owner` and `name` become path segments of
a file-store id, so each must be a plain name of the kind hosting providers
actually issue."""

import pytest
from pydantic import ValidationError

from onyx.repo_archives.models import RepoRef


def _repo_ref(owner: str = "org", name: str = "repo") -> RepoRef:
    return RepoRef(provider="test", host="test.local", owner=owner, name=name)


@pytest.mark.parametrize(
    "owner", ["org", "group/subgroup", "a/b/c", "dot.org", "-lead", "under_score"]
)
def test_valid_owner_paths(owner: str) -> None:
    assert _repo_ref(owner=owner).owner == owner


@pytest.mark.parametrize(
    "bad",
    ["", "..", "/org", "org/", "a/../b", "a//b", ".", "a\\b", "a b", "org\x00", "C:"],
)
def test_invalid_owner_is_rejected(bad: str) -> None:
    with pytest.raises(ValidationError):
        _repo_ref(owner=bad)


@pytest.mark.parametrize("bad", ["", "..", "/repo", "repo/", "a/../b", "."])
def test_invalid_name_is_rejected(bad: str) -> None:
    with pytest.raises(ValidationError):
        _repo_ref(name=bad)


def test_key_prefix_and_display() -> None:
    ref = _repo_ref(owner="group/subgroup", name="repo")
    assert ref.key_prefix == "test/test.local/group/subgroup/repo/"
    assert ref.display == "group/subgroup/repo"
