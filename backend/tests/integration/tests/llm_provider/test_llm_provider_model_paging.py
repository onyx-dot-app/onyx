"""The user-facing provider listing holds at most one page of models per
provider and says where the rest starts. GET /llm/provider/{id}/models serves
the rest by offset or by name search, under the same access rules."""

from onyx.llm.constants import LLM_PROVIDER_MODEL_PAGE_SIZE
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.test_models import DATestUser

EXTRA_MODEL_COUNT = 5


def _listed_provider(user: DATestUser, provider_id: int) -> dict:
    response = client.get(f"{API_SERVER_URL}/llm/provider", headers=user.headers)
    response.raise_for_status()
    return next(p for p in response.json()["providers"] if p["id"] == provider_id)


def _model_page(user: DATestUser, provider_id: int, **params: str | int) -> dict:
    response = client.get(
        f"{API_SERVER_URL}/llm/provider/{provider_id}/models",
        params=params,
        headers=user.headers,
    )
    response.raise_for_status()
    return response.json()


def test_listing_truncates_to_one_page_and_pages_the_rest(
    new_admin_user: DATestUser,
) -> None:
    model_names = [
        f"paged-model-{i:05d}"
        for i in range(LLM_PROVIDER_MODEL_PAGE_SIZE + EXTRA_MODEL_COUNT - 1)
    ]
    provider = LLMProviderManager.create(
        user_performing_action=new_admin_user,
        default_model_name="paged-default",
        model_names=model_names,
        set_as_default=False,
    )
    all_names = {"paged-default", *model_names}

    listed = _listed_provider(new_admin_user, provider.id)
    first_page_names = {mc["name"] for mc in listed["model_configurations"]}
    assert len(first_page_names) == LLM_PROVIDER_MODEL_PAGE_SIZE
    assert listed["next_model_configuration_offset"] == LLM_PROVIDER_MODEL_PAGE_SIZE

    rest = _model_page(new_admin_user, provider.id, offset=LLM_PROVIDER_MODEL_PAGE_SIZE)
    rest_names = {mc["name"] for mc in rest["model_configurations"]}
    assert len(rest_names) == EXTRA_MODEL_COUNT
    assert rest["next_offset"] is None
    assert first_page_names.isdisjoint(rest_names)
    assert first_page_names | rest_names == all_names


def test_listing_pins_the_default_model_past_the_first_page(
    new_admin_user: DATestUser,
) -> None:
    model_names = [f"aaa-model-{i:05d}" for i in range(LLM_PROVIDER_MODEL_PAGE_SIZE)]
    provider = LLMProviderManager.create(
        user_performing_action=new_admin_user,
        default_model_name="zzz-default",
        model_names=model_names,
        set_as_default=True,
    )

    listed = _listed_provider(new_admin_user, provider.id)
    names = [mc["name"] for mc in listed["model_configurations"]]
    assert "zzz-default" in names, "the workspace default sorts past the page"
    assert len(names) == LLM_PROVIDER_MODEL_PAGE_SIZE + 1
    assert listed["next_model_configuration_offset"] == LLM_PROVIDER_MODEL_PAGE_SIZE


def test_listing_marks_a_small_provider_complete(
    new_admin_user: DATestUser,
) -> None:
    provider = LLMProviderManager.create(
        user_performing_action=new_admin_user, set_as_default=False
    )

    listed = _listed_provider(new_admin_user, provider.id)
    assert listed["next_model_configuration_offset"] is None


def test_model_search_matches_unloaded_models(new_admin_user: DATestUser) -> None:
    model_names = [f"filler-{i:05d}" for i in range(LLM_PROVIDER_MODEL_PAGE_SIZE)] + [
        "zz-needle-alpha",
        "zz-needle-beta",
    ]
    provider = LLMProviderManager.create(
        user_performing_action=new_admin_user,
        default_model_name="filler-default",
        model_names=model_names,
        set_as_default=False,
    )

    listed = _listed_provider(new_admin_user, provider.id)
    assert not any("needle" in mc["name"] for mc in listed["model_configurations"]), (
        "the needles sort past the first page, so they must be unloaded"
    )

    found = _model_page(new_admin_user, provider.id, query="NEEDLE")
    assert {mc["name"] for mc in found["model_configurations"]} == {
        "zz-needle-alpha",
        "zz-needle-beta",
    }

    # LIKE metacharacters in the query are literal, not wildcards.
    assert (
        _model_page(new_admin_user, provider.id, query="%")["model_configurations"]
        == []
    )


def test_model_page_denied_without_provider_access(
    admin_user: DATestUser, basic_user: DATestUser
) -> None:
    provider = LLMProviderManager.create(
        user_performing_action=admin_user,
        is_public=False,
        set_as_default=False,
    )

    response = client.get(
        f"{API_SERVER_URL}/llm/provider/{provider.id}/models",
        headers=basic_user.headers,
    )
    assert response.status_code == 403
