import pytest

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.github.config import GithubCredentialBinding
from onyx.connectors.gitlab.config import GitlabCredentialBinding
from onyx.connectors.zendesk.config import ZendeskCredentialBinding


def test_same_realm_is_accepted_without_case_scheme_or_trailing_slash() -> None:
    GitlabCredentialBinding(
        gitlab_url="https://GitLab.Example.com/"
    ).validate_credential({"gitlab_url": "gitlab.example.com"})


def test_another_realm_is_rejected() -> None:
    with pytest.raises(ConnectorValidationError):
        GitlabCredentialBinding(
            gitlab_url="https://gitlab.example.com"
        ).validate_credential({"gitlab_url": "https://gitlab.other.com"})


def test_an_empty_config_realm_accepts_every_credential() -> None:
    GitlabCredentialBinding().validate_credential({"gitlab_url": "https://a.com"})
    GitlabCredentialBinding(gitlab_url=" ").validate_credential(
        {"gitlab_url": "https://a.com"}
    )


def test_a_credential_without_a_realm_counts_as_the_default() -> None:
    GithubCredentialBinding(github_base_url="https://github.com").validate_credential(
        {}
    )
    with pytest.raises(ConnectorValidationError):
        GithubCredentialBinding(
            github_base_url="https://ghe.example.com"
        ).validate_credential({})


def test_a_credential_without_a_realm_or_default_is_accepted() -> None:
    GitlabCredentialBinding(
        gitlab_url="https://gitlab.example.com"
    ).validate_credential({})


def test_a_subdomain_matches_its_full_host() -> None:
    ZendeskCredentialBinding(
        zendesk_subdomain="https://acme.zendesk.com"
    ).validate_credential({"zendesk_subdomain": "acme"})
