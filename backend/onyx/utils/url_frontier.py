import heapq
import ipaddress
import socket
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from functools import lru_cache
from typing import Dict
from typing import Optional
from typing import Set
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from onyx.configs.app_configs import WEB_CONNECTOR_VALIDATE_URLS
from onyx.utils.logger import setup_logger

logger = setup_logger()


def get_ttl_hash(seconds: int = 3600) -> int:
    return round(time.time() / seconds)


@dataclass
class URLInfo:
    __slots__ = ["url", "timestamp"]
    url: str
    timestamp: datetime


class DomainQueue:
    """Manages URL queue for a specific domain with rate limiting capabilities."""

    def __init__(self) -> None:
        self._urls: deque[URLInfo] = deque()
        self._backoff_until: datetime = datetime.now()  # Rate limiting

    def add_url(self, url_info: URLInfo) -> None:
        self._urls.append(url_info)

    def get_next_url(self) -> Optional[URLInfo]:
        return self._urls.popleft() if self._urls else None

    def is_ready(self) -> bool:
        now = datetime.now()
        return now >= self._backoff_until


class URLFrontierError(Exception):
    """Base exception for URL Frontier errors"""


class URLValidationError(URLFrontierError):
    """Raised when URL fails validation"""


class RobotsError(URLFrontierError):
    """Raised when robots.txt parsing fails"""


class DNSError(URLFrontierError):
    """Raised when DNS resolution fails"""


class RobotsValidator:
    """Validates URLs against robots.txt rules with caching support.

    Attributes:
        __parsers: Cache of parsed robots.txt files by domain
        __cache_duration: How long to cache robots.txt content
        __cache_timestamps: When each robots.txt was last fetched
        __missing_robots: Set of domains known to have no robots.txt
    """

    def __init__(self) -> None:
        self.__missing_robots: Set[str] = set()

    @staticmethod
    @lru_cache(maxsize=50)
    def _fetch_robots_txt(domain: str, ttl_hash: int) -> Optional[RobotFileParser]:
        parser = RobotFileParser()
        try:
            robots_url = f"https://{domain}/robots.txt"
            parser.set_url(robots_url)
            parser.read()
            return parser
        except Exception:
            return None

    def is_allowed(self, url: str, user_agent: str = "*") -> bool:
        try:
            domain = urlparse(url).netloc
            if domain in self.__missing_robots:
                logger.info(f"Skipping robots.txt check for {domain}")
                return True

            parser = self._fetch_robots_txt(domain, get_ttl_hash())
            if parser is None:
                self.__missing_robots.add(domain)
                return True

            return parser.can_fetch(user_agent, url)
        except Exception as e:
            logger.error(f"Error checking robots.txt for {url}: {str(e)}")
            raise RobotsError(f"Failed to check robots.txt: {str(e)}") from e


class DNSValidator:
    """Validates URLs through DNS resolution with caching support using lru_cache."""

    @staticmethod
    @lru_cache(maxsize=100)
    def _validate_hostname(hostname: str, ttl_hash: int) -> bool:
        try:
            info = socket.getaddrinfo(hostname, None)
            for address in info:
                ip = address[4][0]
                if not ipaddress.ip_address(ip).is_global:
                    logger.warning(f"Non-global IP address: {ip}")
                    return False
            return True
        except socket.gaierror:
            return False

    def is_valid(self, url: str) -> bool:
        try:
            if not WEB_CONNECTOR_VALIDATE_URLS:
                logger.debug("URL validation disabled, skipping DNS check")
                return True

            parse = urlparse(url)
            logger.debug(f"Validating DNS for {parse.hostname}")

            if parse.scheme not in ("http", "https"):
                raise URLValidationError(f"Invalid scheme: {parse.scheme}")

            if not parse.hostname:
                raise URLValidationError("Missing hostname")

            return self._validate_hostname(parse.hostname, get_ttl_hash())

        except URLValidationError as e:
            logger.warning(str(e))
            return False
        except Exception as e:
            logger.error(f"Unexpected error validating URL {url}: {str(e)}")
            return False


class URLFrontier:
    """Manages URL crawling queue with politeness and load balancing across queues.

    Implements a politeness policy per domain and maintains url load balancing
    using a priority queue approach.
    """

    def __init__(self) -> None:
        logger.info("Initializing URL Frontier")
        self.__domain_queues: Dict[str, DomainQueue] = {}
        self.__visited_urls: Set[str] = set()
        self.__robots_validator = RobotsValidator()
        self.__domain_priority_queue: list[tuple[float, str]] = []
        self.__dns_validator = DNSValidator()

    def add_url(self, url: str | None) -> bool:
        try:
            logger.debug(f"Attempting to add URL: {url}")

            # Handle None and empty strings
            if not url:
                logger.warning("URL is None or empty")
                return False

            if not isinstance(url, str):
                logger.warning(f"URL must be a string, got {type(url)}")
                return False

            # Basic URL format validation
            try:
                parsed = urlparse(url)
                if not all([parsed.scheme, parsed.netloc]):
                    logger.warning(f"Invalid URL format: {url}")
                    return False

                if parsed.scheme not in ["http", "https"]:
                    logger.warning(f"Unsupported URL scheme: {parsed.scheme}")
                    return False
            except Exception as e:
                logger.warning(f"URL parsing failed for {url}: {str(e)}")
                return False

            if url in self.__visited_urls:
                logger.debug(f"URL already visited: {url}")
                return False

            self.__visited_urls.add(url)

            if not self.__robots_validator.is_allowed(url):
                logger.info(f"URL blocked by robots.txt: {url}")
                return False

            if not self.__dns_validator.is_valid(url):
                logger.info(f"URL failed DNS validation: {url}")
                return False

            domain = parsed.netloc
            if not domain:
                raise URLValidationError("Unable to extract domain from URL")

            if domain not in self.__domain_queues:
                self.__domain_queues[domain] = DomainQueue()
                heapq.heappush(self.__domain_priority_queue, (time.time(), domain))

            url_info = URLInfo(url=url, timestamp=datetime.now())
            self.__domain_queues[domain].add_url(url_info)
            return True

        except URLFrontierError as e:
            logger.warning(f"Failed to add URL {url}: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error adding URL {url}: {str(e)}")
            return False

    def get_next_url(self) -> Optional[str]:
        """Get next URL to crawl, respecting politeness delays.

        Returns:
            Optional[URLInfo]: Next URL to crawl or None if queue empty
        """
        domain = None
        queue = None
        try:
            logger.debug("Fetching next URL from frontier")
            while self.__domain_priority_queue:
                now = datetime.now()

                # Check if all domains are rate-limited
                if all(not queue.is_ready() for queue in self.__domain_queues.values()):
                    # Find earliest available time
                    earliest_time = min(
                        queue._backoff_until for queue in self.__domain_queues.values()
                    )
                    """ To ensure sleep duration is atleast 1 millisecond,
                    if the difference is less than 1 millisecond which will
                    result in 0 sleep time"""
                    sleep_duration = max(0.001, (earliest_time - now).total_seconds())
                    if sleep_duration > 0:
                        # If we didn't put it in sleep, the while loop would run continuously
                        logger.info(f"Sleeping for {sleep_duration} seconds")
                        time.sleep(sleep_duration)

                _, domain = heapq.heappop(self.__domain_priority_queue)
                queue = self.__domain_queues[domain]
                if not queue.is_ready():
                    # Re-add with updated priority
                    heapq.heappush(self.__domain_priority_queue, (time.time(), domain))
                    continue

                url_info = queue.get_next_url()
                if url_info:
                    # Re-add domain to priority queue if it has more URLs
                    if queue._urls:
                        heapq.heappush(
                            self.__domain_priority_queue, (time.time(), domain)
                        )
                    else:
                        self.__domain_queues.pop(domain, None)

                    return url_info.url

        except Exception as e:
            logger.error(f"Error retrieving next URL: {str(e)}")
            # Re-add domain to queue if there was an error
            if domain and queue and queue._urls:
                heapq.heappush(self.__domain_priority_queue, (time.time(), domain))

        return None

    def has_next_url(self) -> bool:
        """Check if any domain queues have URLs to process.

        Returns:
            bool: True if there are URLs to process, False otherwise
        """
        try:
            # Check if any domain queue has URLs
            if not self.__domain_queues:
                return False
            return any(
                queue._urls
                for queue in self.__domain_queues.values()
                if queue is not None
            )
        except Exception as e:
            logger.error(f"Error checking for next URL: {str(e)}")
            return False

    def handle_ratelimit(self, url: str, retry_after: Optional[int] = None) -> None:
        """Handle rate limiting for a domain.

        Args:
            url: Rate limited URL
            retry_after: Delay in seconds from server
        """
        try:
            domain = urlparse(url).netloc
            if not domain:
                raise URLValidationError("Unable to extract domain from URL")

            queue = self.__domain_queues.get(domain)
            if not queue:
                queue = DomainQueue()
                self.__domain_queues[domain] = queue

            backoff = max(retry_after or 5, 1)  # Ensure positive backoff
            queue._backoff_until = datetime.now() + timedelta(seconds=backoff)

            queue.add_url(URLInfo(url=url, timestamp=datetime.now()))

            heapq.heappush(self.__domain_priority_queue, (time.time(), domain))

            logger.info(f"Rate limited {domain} - backing off {backoff}s")

        except Exception as e:
            msg = f"Error handling rate limit for {url}: {str(e)}"
            logger.error(msg)
