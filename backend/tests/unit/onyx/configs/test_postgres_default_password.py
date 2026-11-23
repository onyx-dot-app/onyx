from onyx.configs.app_configs import _default_postgres_password_vars


def test_default_passwords_flagged() -> None:
    assert _default_postgres_password_vars("password", "password") == [
        "POSTGRES_PASSWORD",
        "DB_READONLY_PASSWORD",
    ]


def test_only_default_password_flagged() -> None:
    assert _default_postgres_password_vars("a-strong-secret", "password") == [
        "DB_READONLY_PASSWORD"
    ]
    assert _default_postgres_password_vars("password", "a-strong-secret") == [
        "POSTGRES_PASSWORD"
    ]


def test_strong_passwords_not_flagged() -> None:
    assert _default_postgres_password_vars("a-strong-secret", "another-secret") == []
