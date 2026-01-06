"""
Tests for disposable email validation.
"""

from onyx.auth.disposable_email_validator import DisposableEmailValidator
from onyx.auth.disposable_email_validator import is_disposable_email


class TestDisposableEmailValidator:
    """Test the DisposableEmailValidator class."""

    def test_singleton_pattern(self) -> None:
        """Test that DisposableEmailValidator is a singleton."""
        validator1 = DisposableEmailValidator()
        validator2 = DisposableEmailValidator()
        assert validator1 is validator2

    def test_fallback_domains_included(self) -> None:
        """Test that fallback domains are always included."""
        validator = DisposableEmailValidator()
        domains = validator.get_domains()

        # Check that our hardcoded fallback domains are present
        assert "trashlify.com" in domains
        assert "10minutemail.com" in domains
        assert "guerrillamail.com" in domains
        assert "mailinator.com" in domains
        assert "tempmail.com" in domains
        assert "throwaway.email" in domains
        assert "yopmail.com" in domains

    def test_is_disposable_trashlify(self) -> None:
        """Test that trashlify.com emails are detected as disposable."""
        assert is_disposable_email("test@trashlify.com") is True
        assert is_disposable_email("user123@trashlify.com") is True
        assert is_disposable_email("4q4k99yca1@trashlify.com") is True

    def test_is_disposable_other_known_domains(self) -> None:
        """Test detection of other known disposable domains."""
        disposable_emails = [
            "test@10minutemail.com",
            "user@guerrillamail.com",
            "temp@mailinator.com",
            "fake@tempmail.com",
            "throw@throwaway.email",
            "yop@yopmail.com",
        ]

        for email in disposable_emails:
            assert is_disposable_email(email) is True, f"{email} should be disposable"

    def test_is_not_disposable_legitimate_domains(self) -> None:
        """Test that legitimate email domains are not flagged."""
        legitimate_emails = [
            "user@gmail.com",
            "employee@company.com",
            "admin@onyx.app",
            "test@outlook.com",
            "person@yahoo.com",
            "contact@protonmail.com",
        ]

        for email in legitimate_emails:
            assert (
                is_disposable_email(email) is False
            ), f"{email} should not be disposable"

    def test_case_insensitive(self) -> None:
        """Test that domain checking is case-insensitive."""
        assert is_disposable_email("test@TRASHLIFY.COM") is True
        assert is_disposable_email("test@Trashlify.Com") is True
        assert is_disposable_email("test@TrAsHlIfY.cOm") is True

    def test_invalid_email_formats(self) -> None:
        """Test handling of invalid email formats."""
        assert is_disposable_email("") is False
        assert is_disposable_email("notanemail") is False
        assert is_disposable_email("@trashlify.com") is False
        assert is_disposable_email("test@") is False
        assert is_disposable_email("@") is False

    def test_email_with_subdomains(self) -> None:
        """Test that emails with subdomains are handled correctly."""
        # The domain should be the last part after @
        assert is_disposable_email("user@mail.trashlify.com") is False
        # Only exact domain matches should trigger

    def test_validator_instance_methods(self) -> None:
        """Test the validator instance methods directly."""
        validator = DisposableEmailValidator()

        # Test is_disposable method
        assert validator.is_disposable("test@trashlify.com") is True
        assert validator.is_disposable("test@gmail.com") is False

        # Test invalid inputs
        assert validator.is_disposable("") is False
        assert validator.is_disposable("invalid") is False
        assert validator.is_disposable("@trashlify.com") is False
