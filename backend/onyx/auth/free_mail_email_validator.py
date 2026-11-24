"""
Free-mail domains: addresses that are not tied to a company.

The playground refuses them at sign-up and asks for a work email. Two
sources, one answer: a curated list ships with the code, so the common
providers are refused even when the download fails, and HubSpot's list of
free-mail providers is downloaded on top of it and refreshed hourly.

Only the playground sign-up check calls this. Cloud never downloads the list.
"""

from onyx.auth.domain_blocklist import RemoteDomainBlocklist, normalize_domains
from onyx.configs.app_configs import FREE_MAIL_DOMAINS_URL

# A download that is truncated or not the list must not replace a good one.
# HubSpot's list has about 4,800 domains.
MIN_DOWNLOADED_DOMAINS = 1000

# Always refused, downloaded list or not. Covers what HubSpot's list misses
# (proton.me, pm.me, hey.com, tuta, the Apple relay) and the big providers.
CURATED_FREE_MAIL_DOMAINS: frozenset[str] = frozenset(
    {
        # Google
        "gmail.com",
        "googlemail.com",
        # Microsoft
        "outlook.com",
        "outlook.de",
        "outlook.fr",
        "outlook.es",
        "outlook.it",
        "outlook.jp",
        "outlook.com.au",
        "hotmail.com",
        "hotmail.co.uk",
        "hotmail.fr",
        "hotmail.de",
        "hotmail.it",
        "hotmail.es",
        "hotmail.nl",
        "hotmail.pl",
        "hotmail.pt",
        "hotmail.ro",
        "hotmail.ru",
        "hotmail.sa",
        "hotmail.se",
        "hotmail.tr",
        "hotmail.tw",
        "hotmail.ua",
        "hotmail.us",
        "hotmail.vn",
        "hotmail.za",
        "hotmail.zw",
        "live.com",
        "live.co.uk",
        "live.fr",
        "live.de",
        "live.nl",
        "msn.com",
        # Yahoo
        "yahoo.com",
        "yahoo.co.uk",
        "yahoo.co.in",
        "yahoo.co.jp",
        "yahoo.com.br",
        "yahoo.de",
        "yahoo.fr",
        "yahoo.es",
        "yahoo.it",
        "yahoo.ca",
        "ymail.com",
        "rocketmail.com",
        # Apple, including Hide My Email relays
        "icloud.com",
        "me.com",
        "mac.com",
        "privaterelay.appleid.com",
        # AOL
        "aol.com",
        "aim.com",
        # Proton
        "proton.me",
        "protonmail.com",
        "protonmail.ch",
        "pm.me",
        # GMX and web.de
        "gmx.com",
        "gmx.de",
        "gmx.net",
        "gmx.at",
        "gmx.ch",
        "gmx.us",
        "web.de",
        # mail.com
        "mail.com",
        "email.com",
        "usa.com",
        # Yandex and mail.ru
        "yandex.com",
        "yandex.ru",
        "ya.ru",
        "mail.ru",
        "inbox.ru",
        "list.ru",
        "bk.ru",
        # Zoho, Fastmail, HEY, Tuta, Posteo, mailbox.org, Hushmail
        "zoho.com",
        "zohomail.com",
        "fastmail.com",
        "fastmail.fm",
        "hey.com",
        "tutanota.com",
        "tutamail.com",
        "tuta.io",
        "tuta.com",
        "posteo.de",
        "posteo.net",
        "mailbox.org",
        "hushmail.com",
        # China, Korea, India
        "qq.com",
        "163.com",
        "126.com",
        "sina.com",
        "foxmail.com",
        "naver.com",
        "daum.net",
        "hanmail.net",
        "rediffmail.com",
        # European ISPs and portals
        "laposte.net",
        "orange.fr",
        "wanadoo.fr",
        "free.fr",
        "sfr.fr",
        "t-online.de",
        "freenet.de",
        "libero.it",
        "virgilio.it",
        "seznam.cz",
        "wp.pl",
        "o2.pl",
        "onet.pl",
        "interia.pl",
        "btinternet.com",
        "sky.com",
        "talktalk.net",
        # North American and Oceanian ISPs
        "comcast.net",
        "verizon.net",
        "att.net",
        "sbcglobal.net",
        "bellsouth.net",
        "cox.net",
        "charter.net",
        "shaw.ca",
        "rogers.com",
        "sympatico.ca",
        "bigpond.com",
        "optusnet.com.au",
        "xtra.co.nz",
    }
)


def _parse_domain_lines(body: bytes) -> set[str]:
    """The list is plain text, one domain per line (HubSpot's CSV). Lines
    that are not hostnames are dropped, so an HTML page yields nothing."""
    text = body.decode("utf-8", errors="replace")
    domains = normalize_domains(text.replace(",", "\n").splitlines())
    if len(domains) < MIN_DOWNLOADED_DOMAINS:
        raise ValueError(
            f"Expected at least {MIN_DOWNLOADED_DOMAINS} domains, got {len(domains)}"
        )
    return domains


def free_mail_domain_blocklist() -> RemoteDomainBlocklist:
    """A new, empty cache of the free-mail domain list."""
    return RemoteDomainBlocklist(
        name="free-mail",
        url=FREE_MAIL_DOMAINS_URL,
        fallback_domains=CURATED_FREE_MAIL_DOMAINS,
        parse=_parse_domain_lines,
    )


# The one instance the app uses: a module is imported once per process. The
# first check answers from the curated list while the download runs.
_blocklist = free_mail_domain_blocklist()


def is_free_mail_email(email: str) -> bool:
    """Whether the email address is on a free-mail domain."""
    return _blocklist.contains_email_domain(email)
