from typing import Any

OPENSEARCH_CLUSTER_SETTINGS: dict[str, Any] = {
    "persistent": {
        # By default, when you index a document to a non-existent index,
        # OpenSearch will automatically create the index. This behavior is
        # undesirable so this function exposes the ability to disable it.
        # See
        # https://docs.opensearch.org/latest/install-and-configure/configuring-opensearch/index/#updating-cluster-settings-using-the-api
        "action.auto_create_index": False,
        # Thresholds for OpenSearch to log slow queries at the server level.
        "cluster.search.request.slowlog.level": "INFO",
        "cluster.search.request.slowlog.threshold.warn": "5s",
        "cluster.search.request.slowlog.threshold.info": "2s",
        "cluster.search.request.slowlog.threshold.debug": "1s",
        "cluster.search.request.slowlog.threshold.trace": "500ms",
    }
}
