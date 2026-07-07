"""Unit tests for the Mattermost connector (no network; fake client)."""
from onyx.connectors.mattermost.connector import _build_doc_id
from onyx.connectors.mattermost.connector import _ms_to_dt
from onyx.connectors.mattermost.connector import MattermostConnector
from onyx.connectors.models import Document
from onyx.connectors.models import HierarchyNode
from onyx.connectors.models import SlimDocument

USERS = {
    "u_alice": {"username": "alice", "email": "alice@x.com", "first_name": "Alice", "last_name": "A"},
    "u_bob": {"username": "bob", "email": "bob@x.com", "first_name": "Bob", "last_name": "B"},
    "bot1": {"username": "bot", "email": "bot@x.com"},
}
TEAMS = [{"id": "t1", "name": "eng", "display_name": "Engineering"}]
CHANNELS = [
    {"id": "c_gen", "team_id": "t1", "type": "O", "name": "general", "display_name": "General", "delete_at": 0},
    {"id": "c_sec", "team_id": "t1", "type": "P", "name": "secret", "display_name": "Secret", "delete_at": 0},
    {"id": "c_old", "team_id": "t1", "type": "O", "name": "old", "display_name": "Old", "delete_at": 999},
    {"id": "c_dm", "team_id": "t1", "type": "D", "name": "dm", "display_name": "dm", "delete_at": 0},
]
# posts keyed by channel; values are {id: post}
POSTS = {
    "c_gen": {
        "r1": {"id": "r1", "create_at": 1000, "update_at": 1000, "root_id": "", "user_id": "u_alice", "message": "Deploy plan", "type": ""},
        "r1a": {"id": "r1a", "create_at": 1500, "update_at": 1500, "root_id": "r1", "user_id": "u_bob", "message": "LGTM", "type": ""},
        "p2": {"id": "p2", "create_at": 2000, "update_at": 2000, "root_id": "", "user_id": "u_alice", "message": "Standalone note", "type": ""},
        "s1": {"id": "s1", "create_at": 2500, "update_at": 2500, "root_id": "", "user_id": "u_alice", "message": "joined", "type": "system_join_channel"},
        "d1": {"id": "d1", "create_at": 2600, "update_at": 2600, "root_id": "", "user_id": "u_bob", "message": "deleted", "type": "", "delete_at": 2700},
    },
    "c_sec": {
        "r3": {"id": "r3", "create_at": 3000, "update_at": 3000, "root_id": "", "user_id": "u_bob", "message": "Secret topic", "type": ""},
    },
    "c_old": {"r9": {"id": "r9", "create_at": 50, "update_at": 50, "root_id": "", "user_id": "u_alice", "message": "old", "type": ""}},
    "c_dm": {"r8": {"id": "r8", "create_at": 60, "update_at": 60, "root_id": "", "user_id": "u_alice", "message": "hi", "type": ""}},
}


class FakeClient:
    def __init__(self) -> None:
        self.base_url = "https://mm.example.com"
        self.thread_calls: list[str] = []

    def get_me(self) -> dict:
        return {"id": "bot1"}

    def get_my_teams(self) -> list[dict]:
        return list(TEAMS)

    def get_channels_for_team(self, user_id: str, team_id: str) -> list[dict]:  # noqa: ARG002
        return [c for c in CHANNELS if c["team_id"] == team_id]

    def get_channel_posts(self, channel_id: str, before=None, per_page=200) -> dict:  # noqa: ARG002
        posts = POSTS.get(channel_id, {})
        order = sorted(posts.keys(), key=lambda pid: posts[pid]["create_at"], reverse=True)
        return {"order": order, "posts": dict(posts), "prev_post_id": ""}

    def get_thread(self, root_id: str) -> dict:
        self.thread_calls.append(root_id)
        # return the root plus any replies whose root_id == root_id, across channels
        thread = {}
        for chan in POSTS.values():
            for pid, p in chan.items():
                if pid == root_id or p.get("root_id") == root_id:
                    thread[pid] = p
        return {"order": list(thread.keys()), "posts": thread}

    def get_user(self, user_id: str) -> dict:
        return dict(USERS.get(user_id, {}))


def _make_connector(**kwargs) -> MattermostConnector:
    c = MattermostConnector(**kwargs)
    c.client = FakeClient()  # bypass load_credentials
    return c


def _run(connector) -> tuple[list[Document], list[HierarchyNode]]:
    """Drive the checkpoint loop to completion; collect docs + hierarchy nodes."""
    cp = connector.build_dummy_checkpoint()
    docs: list[Document] = []
    nodes: list[HierarchyNode] = []
    guard = 0
    while cp.has_more:
        guard += 1
        assert guard < 50, "checkpoint loop did not terminate"
        gen = connector.load_from_checkpoint(0, 9_999_999_999, cp)
        try:
            while True:
                item = next(gen)
                if isinstance(item, Document):
                    docs.append(item)
                elif isinstance(item, HierarchyNode):
                    nodes.append(item)
        except StopIteration as stop:
            cp = stop.value
    return docs, nodes


def test_full_index_emits_expected_threads() -> None:
    docs, nodes = _run(_make_connector())
    ids = {d.id for d in docs}
    # archived (c_old) + DM (c_dm) excluded by default; system + deleted posts skipped
    assert ids == {"c_gen__r1", "c_gen__p2", "c_sec__r3"}
    # one hierarchy node per visited channel
    assert {n.raw_node_id for n in nodes} == {"c_gen", "c_sec"}


def test_thread_grouping_and_doc_fields() -> None:
    docs, _ = _run(_make_connector())
    by_id = {d.id: d for d in docs}
    thread = by_id["c_gen__r1"]
    # root + reply collapsed into one doc, chronological
    assert [s.text for s in thread.sections] == ["Alice A: Deploy plan", "Bob B: LGTM"]
    # doc_updated_at = max(update_at) across the thread (the reply at 1500ms)
    assert thread.doc_updated_at == _ms_to_dt(1500)
    assert thread.sections[0].link == "https://mm.example.com/eng/pl/r1"
    assert thread.semantic_identifier == "Alice A in #General: Deploy plan"
    assert thread.metadata["Team"] == "Engineering"
    assert thread.metadata["Channel"] == "General"
    assert thread.metadata["is_private"] == "False"
    assert thread.primary_owners and thread.primary_owners[0].email == "alice@x.com"
    assert thread.parent_hierarchy_raw_node_id == "c_gen"
    # standalone post -> single-section doc
    assert len(by_id["c_gen__p2"].sections) == 1


def test_private_flag_marks_metadata() -> None:
    docs, _ = _run(_make_connector())
    sec = {d.id: d for d in docs}["c_sec__r3"]
    assert sec.metadata["is_private"] == "True"


def test_include_filter_limits_channels() -> None:
    docs, _ = _run(_make_connector(channels=["general"]))
    assert {d.id for d in docs} == {"c_gen__r1", "c_gen__p2"}


def test_exclude_filter_drops_channel() -> None:
    docs, _ = _run(_make_connector(exclude_channels=["secret"]))
    assert all(not d.id.startswith("c_sec") for d in docs)


def test_regex_include() -> None:
    docs, _ = _run(_make_connector(channels=["gen.*"], channel_regex_enabled=True))
    assert {d.id for d in docs} == {"c_gen__r1", "c_gen__p2"}


def test_include_dms_and_private_toggle() -> None:
    docs, _ = _run(_make_connector(include_dms=True))
    assert any(d.id.startswith("c_dm") for d in docs)
    docs2, _ = _run(_make_connector(include_private_channels=False))
    assert all(not d.id.startswith("c_sec") for d in docs2)


def test_include_archived_toggle() -> None:
    docs, _ = _run(_make_connector(include_archived=True))
    assert any(d.id.startswith("c_old") for d in docs)


def test_incremental_start_filters_old_posts() -> None:
    # start after r1/r1a/p2 (2000ms) => only newer threads survive; c_gen has none newer
    connector = _make_connector()
    cp = connector.build_dummy_checkpoint()
    docs: list[Document] = []
    guard = 0
    start_secs = 2.4  # 2400 ms -> excludes r1(1000),r1a(1500),p2(2000); c_sec r3(3000) kept
    while cp.has_more:
        guard += 1
        assert guard < 50
        gen = connector.load_from_checkpoint(start_secs, 9_999_999_999, cp)
        try:
            while True:
                item = next(gen)
                if isinstance(item, Document):
                    docs.append(item)
        except StopIteration as stop:
            cp = stop.value
    assert {d.id for d in docs} == {"c_sec__r3"}


def test_checkpoint_json_resume_no_duplicates() -> None:
    connector = _make_connector()
    cp = connector.build_dummy_checkpoint()
    seen_ids: list[str] = []
    guard = 0
    while cp.has_more:
        guard += 1
        assert guard < 50
        gen = connector.load_from_checkpoint(0, 9_999_999_999, cp)
        try:
            while True:
                item = next(gen)
                if isinstance(item, Document):
                    seen_ids.append(item.id)
        except StopIteration as stop:
            cp = stop.value
        # serialize + deserialize between every step (simulates resume)
        cp = connector.validate_checkpoint_json(cp.model_dump_json())
    assert len(seen_ids) == len(set(seen_ids)), "duplicate documents across resume"


def test_slim_docs_match_doc_ids() -> None:
    connector = _make_connector()
    slim_ids = set()
    for batch in connector.retrieve_all_slim_docs():
        for s in batch:
            assert isinstance(s, SlimDocument)
            slim_ids.add(s.id)
    assert slim_ids == {"c_gen__r1", "c_gen__p2", "c_sec__r3"}


def test_build_doc_id_stable() -> None:
    assert _build_doc_id("c1", "p1") == "c1__p1"
