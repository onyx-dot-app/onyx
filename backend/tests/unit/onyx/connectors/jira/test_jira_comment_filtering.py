"""Unit tests for Jira comment visibility filtering."""

import pytest

from onyx.connectors.jira.utils import get_comment_strs


def test_basic_comment_extraction() -> None:
    """Test basic comment extraction without any filtering."""
    issue = {
        "fields": {
            "comment": {
                "comments": [
                    {"author": {"emailAddress": "user@example.com"}, "body": "Test comment 1"},
                    {"author": {"emailAddress": "user2@example.com"}, "body": "Test comment 2"},
                ]
            }
        }
    }
    
    comments = get_comment_strs(issue)
    assert len(comments) == 2
    assert "Test comment 1" in comments
    assert "Test comment 2" in comments


def test_email_blacklist() -> None:
    """Test that email blacklist correctly filters comments."""
    issue = {
        "fields": {
            "comment": {
                "comments": [
                    {"author": {"emailAddress": "bot@example.com"}, "body": "Bot comment"},
                    {"author": {"emailAddress": "user@example.com"}, "body": "User comment"},
                ]
            }
        }
    }
    
    comments = get_comment_strs(issue, comment_email_blacklist=("bot@example.com",))
    assert len(comments) == 1
    assert "User comment" in comments
    assert "Bot comment" not in comments


def test_skip_restricted_flag_false() -> None:
    """Test that visibility-restricted comments are included when skip_restricted=False."""
    issue = {
        "fields": {
            "comment": {
                "comments": [
                    {
                        "author": {"emailAddress": "user@example.com"},
                        "body": "Public comment",
                    },
                    {
                        "author": {"emailAddress": "user@example.com"},
                        "body": "Restricted comment",
                        "visibility": {"type": "group", "value": "jira-administrators"},
                    },
                ]
            }
        }
    }
    
    comments = get_comment_strs(issue, skip_restricted=False)
    assert len(comments) == 2
    assert "Public comment" in comments
    assert "Restricted comment" in comments


def test_skip_restricted_flag_true() -> None:
    """Test that visibility-restricted comments are excluded when skip_restricted=True."""
    issue = {
        "fields": {
            "comment": {
                "comments": [
                    {
                        "author": {"emailAddress": "user@example.com"},
                        "body": "Public comment",
                    },
                    {
                        "author": {"emailAddress": "user@example.com"},
                        "body": "Restricted comment",
                        "visibility": {"type": "group", "value": "jira-administrators"},
                    },
                ]
            }
        }
    }
    
    comments = get_comment_strs(issue, skip_restricted=True)
    assert len(comments) == 1
    assert "Public comment" in comments
    assert "Restricted comment" not in comments


def test_skip_jsm_internal_flag_false() -> None:
    """Test that JSM internal comments are included when skip_jsm_internal=False."""
    issue = {
        "fields": {
            "comment": {
                "comments": [
                    {
                        "author": {"emailAddress": "agent@example.com"},
                        "body": "Public JSM comment",
                        "jsdPublic": True,
                    },
                    {
                        "author": {"emailAddress": "agent@example.com"},
                        "body": "Internal JSM comment",
                        "jsdPublic": False,
                    },
                ]
            }
        }
    }
    
    comments = get_comment_strs(issue, skip_jsm_internal=False)
    assert len(comments) == 2
    assert "Public JSM comment" in comments
    assert "Internal JSM comment" in comments


def test_skip_jsm_internal_flag_true_jsd_public() -> None:
    """Test that JSM internal comments (jsdPublic=False) are excluded when skip_jsm_internal=True."""
    issue = {
        "fields": {
            "comment": {
                "comments": [
                    {
                        "author": {"emailAddress": "agent@example.com"},
                        "body": "Public JSM comment",
                        "jsdPublic": True,
                    },
                    {
                        "author": {"emailAddress": "agent@example.com"},
                        "body": "Internal JSM comment",
                        "jsdPublic": False,
                    },
                ]
            }
        }
    }
    
    comments = get_comment_strs(issue, skip_jsm_internal=True)
    assert len(comments) == 1
    assert "Public JSM comment" in comments
    assert "Internal JSM comment" not in comments


def test_skip_jsm_internal_sd_public_comment_property() -> None:
    """Test JSM internal comments via sd.public.comment property."""
    issue = {
        "fields": {
            "comment": {
                "comments": [
                    {
                        "author": {"emailAddress": "agent@example.com"},
                        "body": "Public comment via property",
                        "properties": {
                            "sd.public.comment": {"internal": False}
                        },
                    },
                    {
                        "author": {"emailAddress": "agent@example.com"},
                        "body": "Internal comment via property",
                        "properties": {
                            "sd.public.comment": {"internal": True}
                        },
                    },
                ]
            }
        }
    }
    
    comments = get_comment_strs(issue, skip_jsm_internal=True)
    assert len(comments) == 1
    assert "Public comment via property" in comments
    assert "Internal comment via property" not in comments


def test_skip_jsm_internal_fail_closed_missing_internal_value() -> None:
    """Test that comments with sd.public.comment but missing internal value are skipped (fail closed)."""
    issue = {
        "fields": {
            "comment": {
                "comments": [
                    {
                        "author": {"emailAddress": "agent@example.com"},
                        "body": "Normal comment",
                    },
                    {
                        "author": {"emailAddress": "agent@example.com"},
                        "body": "Comment with malformed property",
                        "properties": {
                            "sd.public.comment": {}
                        },
                    },
                ]
            }
        }
    }
    
    comments = get_comment_strs(issue, skip_jsm_internal=True)
    assert len(comments) == 1
    assert "Normal comment" in comments
    assert "Comment with malformed property" not in comments


def test_combined_restrictions() -> None:
    """Test that both skip_restricted and skip_jsm_internal work together."""
    issue = {
        "fields": {
            "comment": {
                "comments": [
                    {
                        "author": {"emailAddress": "user@example.com"},
                        "body": "Public comment",
                    },
                    {
                        "author": {"emailAddress": "user@example.com"},
                        "body": "Restricted comment",
                        "visibility": {"type": "group", "value": "admins"},
                    },
                    {
                        "author": {"emailAddress": "agent@example.com"},
                        "body": "Internal JSM comment",
                        "jsdPublic": False,
                    },
                    {
                        "author": {"emailAddress": "bot@example.com"},
                        "body": "Bot comment",
                    },
                ]
            }
        }
    }
    
    comments = get_comment_strs(
        issue, 
        comment_email_blacklist=("bot@example.com",),
        skip_restricted=True,
        skip_jsm_internal=True
    )
    assert len(comments) == 1
    assert "Public comment" in comments
    assert "Restricted comment" not in comments
    assert "Internal JSM comment" not in comments
    assert "Bot comment" not in comments


def test_jsm_internal_no_jsd_public_field() -> None:
    """Test that comments without jsdPublic field are included when skip_jsm_internal=True."""
    issue = {
        "fields": {
            "comment": {
                "comments": [
                    {
                        "author": {"emailAddress": "user@example.com"},
                        "body": "Comment without jsdPublic",
                    },
                ]
            }
        }
    }
    
    comments = get_comment_strs(issue, skip_jsm_internal=True)
    assert len(comments) == 1
    assert "Comment without jsdPublic" in comments


def test_error_handling_malformed_comment() -> None:
    """Test that malformed comments are handled gracefully."""
    issue = {
        "fields": {
            "comment": {
                "comments": [
                    {
                        "author": {"emailAddress": "user@example.com"},
                        "body": "Valid comment",
                    },
                    None,
                    {
                        "author": None,
                        "body": "Comment with null author",
                    },
                ]
            }
        }
    }
    
    comments = get_comment_strs(issue)
    assert len(comments) >= 1
    assert "Valid comment" in comments
