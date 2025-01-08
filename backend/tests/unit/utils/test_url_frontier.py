import time
from collections.abc import Generator
from unittest.mock import Mock
from unittest.mock import patch

import pytest

from onyx.utils.url_frontier import URLFrontier


class TestURLFrontier:
    @pytest.fixture
    def frontier(self) -> URLFrontier:
        return URLFrontier()

    @pytest.fixture
    def mock_dns_validator(self) -> Generator[Mock, None, None]:
        with patch("onyx.utils.url_frontier.DNSValidator.is_valid") as mock:
            mock.return_value = True
            yield mock

    @pytest.fixture
    def mock_robots_validator(self) -> Generator[Mock, None, None]:
        with patch("onyx.utils.url_frontier.RobotsValidator.is_allowed") as mock:
            mock.return_value = True
            yield mock

    def test_basic_url_operations(
        self,
        frontier: URLFrontier,
        mock_dns_validator: Mock,
        mock_robots_validator: Mock,
    ) -> None:
        """Test basic URL addition and retrieval"""
        test_url = "https://example.com/page1"

        assert frontier.add_url(test_url) is True
        assert frontier.has_next_url() is True
        assert frontier.get_next_url() == test_url
        assert frontier.has_next_url() is False

    def test_duplicate_urls(
        self,
        frontier: URLFrontier,
        mock_dns_validator: Mock,
        mock_robots_validator: Mock,
    ) -> None:
        """Test handling of duplicate URLs"""
        test_url = "https://example.com/page1"

        assert frontier.add_url(test_url) is True
        assert frontier.add_url(test_url) is False
        assert frontier.get_next_url() == test_url
        assert frontier.get_next_url() is None

    def test_invalid_urls(self, frontier: URLFrontier) -> None:
        """Test invalid URL handling"""
        invalid_urls = [None, "", "not_a_url", "ftp://example.com", "http:/example.com"]

        for url in invalid_urls:
            assert frontier.add_url(url) is False

    def test_dns_validation(self, frontier: URLFrontier) -> None:
        """Test DNS validation"""
        with patch("onyx.utils.url_frontier.DNSValidator.is_valid") as mock_dns:
            mock_dns.return_value = False
            assert frontier.add_url("https://invalid-dns.com") is False

            mock_dns.return_value = True
            assert frontier.add_url("https://valid-dns.com") is True

    def test_robots_validation(
        self, frontier: URLFrontier, mock_dns_validator: Mock
    ) -> None:
        """Test robots.txt validation"""
        with patch("onyx.utils.url_frontier.RobotsValidator.is_allowed") as mock_robots:
            mock_robots.return_value = False
            assert frontier.add_url("https://blocked-by-robots.com") is False

            mock_robots.return_value = True
            assert frontier.add_url("https://allowed-by-robots.com") is True

    def test_multiple_domains(
        self,
        frontier: URLFrontier,
        mock_dns_validator: Mock,
        mock_robots_validator: Mock,
    ) -> None:
        """Test handling multiple domains"""
        urls: list[str] = [
            "https://domain1.com/page1",
            "https://domain2.com/page1",
            "https://domain1.com/page2",
        ]

        for url in urls:
            assert frontier.add_url(url)

        retrieved_urls: list[str] = []
        while frontier.has_next_url():
            next_url: str | None = frontier.get_next_url()
            if next_url is not None:
                retrieved_urls.append(next_url)

        assert len(retrieved_urls) == 3
        assert set(retrieved_urls) == set(urls)

    def test_error_handling(self, frontier: URLFrontier) -> None:
        """Test error handling scenarios"""
        with patch(
            "onyx.utils.url_frontier.DNSValidator.is_valid",
            side_effect=Exception("DNS Error"),
        ):
            assert frontier.add_url("https://error.com") is False

        with patch(
            "onyx.utils.url_frontier.RobotsValidator.is_allowed",
            side_effect=Exception("Robots Error"),
        ):
            assert frontier.add_url("https://error.com") is False

    @pytest.mark.parametrize(
        "retry_after,expected_min_delay",
        [
            (5, 5),
            (0, 1),
            (None, 1),
            (-1, 1),
        ],
    )
    def test_rate_limit_delays(
        self, frontier: URLFrontier, retry_after: int, expected_min_delay: int
    ) -> None:
        """Test different rate limit delay scenarios"""
        url = "https://test.com/page"
        frontier.add_url(url)

        start_time = time.time()
        frontier.handle_ratelimit(url, retry_after)
        next_url = frontier.get_next_url()
        elapsed_time = time.time() - start_time

        assert elapsed_time >= expected_min_delay
        assert next_url == url

    def test_empty_frontier(self, frontier: URLFrontier) -> None:
        """Test empty frontier behavior"""
        assert frontier.has_next_url() is False
        assert frontier.get_next_url() is None
