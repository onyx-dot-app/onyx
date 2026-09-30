from onyx.db.enums import AccessType


def test_perm_synced_covers_both_sync_types() -> None:
    assert AccessType.SYNC.is_perm_synced()
    assert AccessType.SYNC_RESTRICTED.is_perm_synced()
    assert not AccessType.PRIVATE.is_perm_synced()
    assert not AccessType.PUBLIC.is_perm_synced()
    assert set(AccessType.perm_synced_types()) == {
        AccessType.SYNC,
        AccessType.SYNC_RESTRICTED,
    }
