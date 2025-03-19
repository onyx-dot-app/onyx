from onyx.utils.logger import setup_logger

logger = setup_logger()


def kg_extraction_base(tenant_id: str, num_chunks: int = 1000) -> None:
    """
    This extraction will create a random sample of chunks to process in order to perform
    clustering and topic modeling.
    """

    logger.info(f"Starting kg extraction for tenant {tenant_id}")


def kg_extraction_full(tenant_id: str) -> None:
    """
    This extraction will try to extract from all chunks that have not been kg-processed yet.
    """

    logger.info(f"Starting kg extraction for tenant {tenant_id}")


def _kg_connector_extraction(
    connector_id: str,
    tenant_id: str,
) -> None:
    logger.info(
        f"Starting kg extraction for connector {connector_id} for tenant {tenant_id}"
    )

    # - grab kg type data from postgres

    # - construct prompt

    # find all documents for the connector that have not been kg-processed

    # - loop for :

    # - grab a number of chunks from vespa

    # - convert them into the KGChunk format

    # - run the extractions in parallel

    # - save the results

    # - mark chunks as processed

    # - update the connector status


#
