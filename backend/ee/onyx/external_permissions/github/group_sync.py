from collections.abc import Generator

from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.github.utils import (
    GitHubGroupSyncCache,
    get_external_user_group,
)
from ee.onyx.external_permissions.utils import credential_json
from onyx.connectors.factory import build_connector_kwargs
from onyx.connectors.github.connector import GithubConnector
from onyx.connectors.github.models import GitHubRepository
from onyx.db.models import ConnectorCredentialPair
from onyx.utils.logger import setup_logger

logger = setup_logger()


def github_group_sync(
    tenant_id: str,  # noqa: ARG001
    cc_pair: ConnectorCredentialPair,
) -> Generator[ExternalUserGroup, None, None]:
    github_connector: GithubConnector = GithubConnector(
        **build_connector_kwargs(
            cc_pair.connector.source, cc_pair.connector.connector_specific_config
        )
    )
    github_connector.load_credentials(credential_json(cc_pair))

    logger.info("Starting GitHub group sync...")
    repos: list[GitHubRepository] = github_connector.fetch_configured_repos()

    cache = GitHubGroupSyncCache()
    for repo in repos:
        for external_group in get_external_user_group(
            repo, github_connector.source_operations, cache
        ):
            logger.info("External group: %s", external_group)
            yield external_group
