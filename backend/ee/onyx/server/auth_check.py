from fastapi import FastAPI

from onyx.server.auth_check import check_router_auth
from onyx.server.auth_check import PUBLIC_ENDPOINT_SPECS


EE_PUBLIC_ENDPOINT_SPECS = PUBLIC_ENDPOINT_SPECS + [
    # needs to be accessible prior to user login
    ("/enterprise-settings", {"GET"}),
    ("/enterprise-settings/logo", {"GET"}),
    ("/enterprise-settings/logotype", {"GET"}),
    ("/enterprise-settings/custom-analytics-script", {"GET"}),
]


def check_ee_router_auth(
    application: FastAPI,
    public_endpoint_specs: list[tuple[str, set[str]]] = EE_PUBLIC_ENDPOINT_SPECS,
) -> None:
    # similar to the open source version of this function, but checking for the EE-only
    # endpoints as well
    check_router_auth(application, public_endpoint_specs)
