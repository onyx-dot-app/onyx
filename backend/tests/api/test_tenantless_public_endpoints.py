import os
import subprocess
import sys
import textwrap


def test_tenantless_public_endpoints_do_not_require_tenant() -> None:
    env = os.environ.copy()
    env["MULTI_TENANT"] = "true"
    env["AUTH_TYPE"] = "cloud"
    env["ENABLE_PAID_ENTERPRISE_EDITION_FEATURES"] = "True"
    backend_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

    script = textwrap.dedent(
        """\
        from fastapi.testclient import TestClient
        from onyx.main import fetch_versioned_implementation
        from onyx.server.auth_check import TENANTLESS_PUBLIC_ENDPOINT_SPECS

        app = fetch_versioned_implementation(
            module="onyx.main", attribute="get_application"
        )()
        client = TestClient(app)

        for path, methods in TENANTLESS_PUBLIC_ENDPOINT_SPECS:
            if "GET" in methods:
                response = client.get(path)
                assert response.status_code < 500, (
                    path,
                    response.status_code,
                    response.text,
                )
                assert "Tenant ID is not set" not in response.text
        """
    )

    subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        cwd=backend_root,
        check=True,
    )
