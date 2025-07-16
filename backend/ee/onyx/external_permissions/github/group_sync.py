from collections.abc import Generator

from github import Repository

from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.github.utils import get_external_user_group
from onyx.connectors.github.connector import GithubConnector
from onyx.db.models import ConnectorCredentialPair
from onyx.utils.logger import setup_logger

logger = setup_logger()


def github_group_sync(
    tenant_id: str,
    cc_pair: ConnectorCredentialPair,
) -> Generator[ExternalUserGroup, None, None]:
    github_connector: GithubConnector = GithubConnector(
        **cc_pair.connector.connector_specific_config
    )
    github_connector.load_credentials(cc_pair.credential.credential_json)
    if not github_connector.github_client:
        raise ValueError("github_client is required")

    logger.info("Starting GitHub group sync...")
    repos: list[Repository.Repository] = []
    if github_connector.repositories:
        if "," in github_connector.repositories:
            # Multiple repositories specified
            repos = github_connector.get_github_repos(github_connector.github_client)
        else:
            # Single repository (backward compatibility)
            repos = [github_connector.get_github_repo(github_connector.github_client)]
    else:
        # All repositories
        repos = github_connector.get_all_repos(github_connector.github_client)

    for repo in repos:
        try:
            for external_group in get_external_user_group(
                repo, github_connector.github_client
            ):
                logger.info(f"External group: {external_group}")
                yield external_group
        except Exception as e:
            logger.error(f"Error processing repository {repo.id} ({repo.name}): {e}")
