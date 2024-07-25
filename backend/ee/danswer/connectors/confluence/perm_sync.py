from danswer.utils.logger import setup_logger


logger = setup_logger()


def confluence_update_db_group() -> None:
    logger.debug("Not yet implemented group sync for confluence, no-op")


def confluence_update_index_acl(cc_pair_id: int) -> None:
    logger.debug("Not yet implemented ACL sync for confluence, no-op")
