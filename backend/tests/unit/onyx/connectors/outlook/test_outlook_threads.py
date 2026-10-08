"""The thread key, the root test, and the rules that turn one mailbox's copy
of a thread into documents from its headers alone."""

import base64
from datetime import datetime, timedelta, timezone

from onyx.connectors.outlook.models import (
    DocumentPlan,
    OutlookMailbox,
    OutlookMessageChange,
    OutlookRecipient,
    ThreadListing,
)
from onyx.connectors.outlook.threads import (
    MAX_MESSAGES_PER_CONVERSATION,
    copy_document_id,
    designated_builder,
    is_thread_root,
    listing_row,
    newest_rows,
    own_document_id,
    plan_documents,
    roster_of,
    thread_document_id,
    thread_key,
)

ROOT = bytes(range(22))
ROOT_INDEX = base64.b64encode(ROOT).decode()
REPLY_INDEX = base64.b64encode(ROOT + bytes(5)).decode()
T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)

ALICE = OutlookMailbox(id="user-1", address="alice@contoso.com")
BOB = OutlookMailbox(id="user-2", address="bob@contoso.com")
CAROL = OutlookMailbox(id="user-3", address="carol@contoso.com")
ROSTER = roster_of([ALICE, BOB, CAROL])
OUTSIDER = "vendor@example.com"


def _recipient(address: str) -> OutlookRecipient:
    return OutlookRecipient(address=address)


def _walked(mailbox: OutlookMailbox) -> bool:
    del mailbox
    return True


def _row(
    message: str,
    sender: OutlookMailbox | None,
    *named: OutlookMailbox,
    minute: int = 0,
    root: bool = False,
) -> ThreadListing:
    everyone = {m.id: m for m in ([sender] if sender else []) + list(named)}
    return ThreadListing(
        key="a",
        conversation_id="conv-a",
        message_id=message,
        received_at=T0 + timedelta(minutes=minute),
        is_root=root,
        sender=sender,
        named=list(everyone.values()),
    )


def _ids(plans: list[DocumentPlan]) -> dict[str, tuple[list[str], set[str]]]:
    return {
        plan.document_id: (plan.message_ids, {r.id for r in plan.readers})
        for plan in plans
    }


def test_a_reply_shares_its_root_message_thread_key() -> None:
    assert thread_key(REPLY_INDEX) == thread_key(ROOT_INDEX)
    assert thread_key(ROOT_INDEX) is not None
    assert is_thread_root(ROOT_INDEX)
    assert not is_thread_root(REPLY_INDEX)


def test_thread_key_is_safe_inside_a_document_id() -> None:
    key = thread_key(base64.b64encode(bytes([251, 255]) * 11).decode())
    assert key is not None
    assert "/" not in key and "+" not in key and "=" not in key
    assert thread_document_id(key) == f"outlook-thread:{key}"
    assert copy_document_id(key, ALICE) == f"outlook-thread:{key}:user-1"
    assert own_document_id(key, ALICE) == f"outlook-thread:{key}:user-1:own"


def test_thread_key_rejects_short_or_malformed_indexes() -> None:
    assert thread_key(base64.b64encode(b"short").decode()) is None
    assert thread_key("not base64!") is None
    assert thread_key("") is None
    assert not is_thread_root("not base64!")


def test_listing_row_maps_headers_to_the_walked_mailboxes() -> None:
    change = OutlookMessageChange(
        id="g-1",
        internet_message_id="<m1@contoso.com>",
        conversation_id="conv-a",
        conversation_index=ROOT_INDEX,
        received_at=T0,
        sender=_recipient(OUTSIDER),
        to_recipients=[_recipient("Bob@Contoso.com"), _recipient(OUTSIDER)],
        cc_recipients=[_recipient(CAROL.address), _recipient(BOB.address)],
    )

    row = listing_row(change, ROSTER)

    assert row is not None
    assert row.message_id == "<m1@contoso.com>"
    assert row.is_root
    assert row.sender is None
    assert [m.id for m in row.named] == [BOB.id, CAROL.id]


def test_listing_row_skips_removals_drafts_and_messages_without_a_thread() -> None:
    removed = OutlookMessageChange(
        id="g-1", conversation_id="conv-a", conversation_index=ROOT_INDEX, removed=True
    )
    draft = OutlookMessageChange(
        id="g-1", conversation_id="conv-a", conversation_index=ROOT_INDEX, is_draft=True
    )
    no_conversation = OutlookMessageChange(id="g-1", conversation_index=ROOT_INDEX)
    no_index = OutlookMessageChange(id="g-1", conversation_id="conv-a")

    for change in (removed, draft, no_conversation, no_index):
        assert listing_row(change, ROSTER) is None


def test_newest_rows_keep_each_message_once_and_cut_to_the_newest() -> None:
    rows = [_row(f"m{i}", ALICE, minute=i) for i in range(5)]
    rows.append(_row("m2", ALICE, minute=2))

    assert [r.message_id for r in newest_rows(rows, keep=3)] == ["m2", "m3", "m4"]


def test_builder_is_the_sender_else_the_lowest_named_mailbox() -> None:
    assert designated_builder(_row("m", CAROL, BOB, root=True), _walked) == CAROL
    assert designated_builder(_row("m", None, CAROL, BOB, root=True), _walked) == BOB
    assert designated_builder(_row("m", None, root=True), _walked) is None


def test_a_mailbox_the_run_cannot_open_is_passed_over_as_builder() -> None:
    """Carol is a guest with no mailbox: she never builds, so Bob does, and
    her copy of the root is nobody's to write."""
    root = _row("root", CAROL, ALICE, BOB, root=True)

    def not_carol(mailbox: OutlookMailbox) -> bool:
        return mailbox.id != CAROL.id

    assert designated_builder(root, not_carol) == ALICE
    assert designated_builder(_row("m", CAROL, root=True), not_carol) is None
    assert _ids(plan_documents([root], ALICE, not_carol)) == {
        thread_document_id("a"): (["root"], {ALICE.id, BOB.id, CAROL.id})
    }
    assert plan_documents([root], BOB, not_carol) == []


def test_builder_writes_the_thread_for_everyone_named_on_every_message() -> None:
    rows = [
        _row("root", ALICE, BOB, CAROL, root=True),
        _row("reply", BOB, ALICE, CAROL, minute=1),
    ]

    plans = _ids(plan_documents(rows, ALICE, _walked))

    assert plans == {
        thread_document_id("a"): (["root", "reply"], {ALICE.id, BOB.id, CAROL.id})
    }
    assert plan_documents(rows, BOB, _walked) == []
    assert plan_documents(rows, CAROL, _walked) == []


def test_a_mailbox_dropped_from_a_reply_gets_the_messages_that_name_it() -> None:
    """Alice wrote to Bob and Carol, Bob answered Alice alone. Carol never
    received the answer, so the thread is Alice's and Bob's, and Alice
    writes Carol a document of the first message."""
    rows = [
        _row("root", ALICE, BOB, CAROL, root=True),
        _row("private", BOB, ALICE, minute=1),
    ]

    plans = _ids(plan_documents(rows, ALICE, _walked))

    assert plans == {
        thread_document_id("a"): (["root", "private"], {ALICE.id, BOB.id}),
        copy_document_id("a", CAROL): (["root"], {CAROL.id}),
    }
    # Carol's own copy holds only the first message, which names the builder.
    assert plan_documents([rows[0]], CAROL, _walked) == []


def test_a_reply_that_left_the_builder_out_is_its_holders_own() -> None:
    """Bob answered Carol without Alice. Alice cannot see it, so Bob and
    Carol each write it as their own document."""
    rows = [
        _row("root", ALICE, BOB, CAROL, root=True),
        _row("aside", BOB, CAROL, minute=1),
    ]

    assert _ids(plan_documents(rows, BOB, _walked)) == {
        own_document_id("a", BOB): (["aside"], {BOB.id})
    }
    assert _ids(plan_documents(rows, CAROL, _walked)) == {
        own_document_id("a", CAROL): (["aside"], {CAROL.id})
    }


def test_a_holder_the_first_message_does_not_name_writes_its_whole_copy() -> None:
    """Carol was added on the reply, so the builder never counts her."""
    rows = [
        _row("root", ALICE, BOB, root=True),
        _row("reply", BOB, ALICE, CAROL, minute=1),
    ]

    assert _ids(plan_documents(rows, CAROL, _walked)) == {
        own_document_id("a", CAROL): (["root", "reply"], {CAROL.id})
    }
    assert _ids(plan_documents(rows, ALICE, _walked)) == {
        thread_document_id("a"): (["root", "reply"], {ALICE.id, BOB.id})
    }


def test_a_copy_without_the_first_message_is_its_holders_own() -> None:
    rows = [_row("reply", BOB, ALICE, minute=1)]

    assert _ids(plan_documents(rows, ALICE, _walked)) == {
        own_document_id("a", ALICE): (["reply"], {ALICE.id})
    }


def test_a_thread_from_outside_to_no_walked_mailbox_is_every_holders_own() -> None:
    rows = [_row("root", None, root=True)]

    assert _ids(plan_documents(rows, ALICE, _walked)) == {
        own_document_id("a", ALICE): (["root"], {ALICE.id})
    }


def test_the_builder_reads_its_thread_even_when_unnamed_on_a_message() -> None:
    """A message Alice was only Bcc'd on names Bob alone. Bob is named on
    every message, so he reads the thread, and the builder always does."""
    rows = [
        _row("root", ALICE, BOB, root=True),
        _row("bcc", BOB, minute=1),
    ]

    assert _ids(plan_documents(rows, ALICE, _walked)) == {
        thread_document_id("a"): (["root", "bcc"], {ALICE.id, BOB.id})
    }


def test_the_thread_is_cut_to_the_newest_messages_but_the_root_still_chooses() -> None:
    rows = [_row("root", BOB, ALICE, root=True)] + [
        _row(f"m{i}", ALICE, BOB, minute=i + 1)
        for i in range(MAX_MESSAGES_PER_CONVERSATION + 5)
    ]

    plans = plan_documents(rows, BOB, _walked)

    assert [p.document_id for p in plans] == [thread_document_id("a")]
    assert len(plans[0].message_ids) == MAX_MESSAGES_PER_CONVERSATION
    assert "root" not in plans[0].message_ids
    assert plan_documents(rows, ALICE, _walked) == []


def test_an_empty_copy_yields_nothing() -> None:
    assert plan_documents([], ALICE, _walked) == []
