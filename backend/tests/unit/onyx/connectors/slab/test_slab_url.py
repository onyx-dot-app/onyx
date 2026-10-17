import pytest

from onyx.connectors.slab.connector import get_slab_url_from_title_id


@pytest.mark.parametrize(
    "slab_base_url, title, page_id, expected",
    [
        (
            "https://onyx-test.slab.com/",
            "Learn about Posts",
            "jcp6cohu",
            "https://onyx-test.slab.com/posts/learn-about-posts-jcp6cohu",
        ),
        (
            "https://myteam.slab.com",
            "Hello World",
            "abc123",
            "https://myteam.slab.com/posts/hello-world-abc123",
        ),
        (
            "https://myteam.slab.com/",
            "Title with   multiple   spaces",
            "id1",
            "https://myteam.slab.com/posts/title-with-multiple-spaces-id1",
        ),
        (
            "https://myteam.slab.com/",
            "Title with special chars !@#$%",
            "id1",
            "https://myteam.slab.com/posts/title-with-special-chars-id1",
        ),
        (
            "https://myteam.slab.com/",
            "Café résumé",
            "id1",
            "https://myteam.slab.com/posts/cafe-resume-id1",
        ),
    ],
)
def test_get_slab_url_from_title_id(
    slab_base_url: str, title: str, page_id: str, expected: str
) -> None:
    assert get_slab_url_from_title_id(slab_base_url, title, page_id) == expected
