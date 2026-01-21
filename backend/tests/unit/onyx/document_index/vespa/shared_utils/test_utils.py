from onyx.utils.text_processing import remove_invalid_unicode_chars


def test_remove_invalid_unicode_chars() -> None:
    """Test that invalid Unicode characters are properly removed."""
    # Test removal of illegal XML character 0xFDDB
    text_with_illegal_char = "Valid text \ufddb more text"
    sanitized = remove_invalid_unicode_chars(text_with_illegal_char)
    assert "\ufddb" not in sanitized
    assert sanitized == "Valid text  more text"

    # Test that valid characters are preserved
    valid_text = "Hello, world! 你好世界"
    assert remove_invalid_unicode_chars(valid_text) == valid_text

    # Test multiple invalid characters including 0xFDDB
    text_with_multiple_illegal = "\x00Hello\ufddb World\ufffe!"
    sanitized = remove_invalid_unicode_chars(text_with_multiple_illegal)
    assert all(c not in sanitized for c in ["\x00", "\ufddb", "\ufffe"])
    assert sanitized == "Hello World!"


def test_remove_surrogate_characters() -> None:
    """Test removal of unpaired UTF-16 surrogates that cause 'surrogates not allowed' errors.

    This is the specific error seen when indexing Drive documents with Cohere:
    'utf-8' codec can't encode character '\\udc00' in position X: surrogates not allowed
    """
    # Test low surrogate (the exact error case from Drive indexing with Cohere)
    text_with_low_surrogate = "Text before \udc00 text after"
    sanitized = remove_invalid_unicode_chars(text_with_low_surrogate)
    assert "\udc00" not in sanitized
    assert sanitized == "Text before  text after"

    # Test high surrogate
    text_with_high_surrogate = "Start \ud800 end"
    sanitized = remove_invalid_unicode_chars(text_with_high_surrogate)
    assert "\ud800" not in sanitized
    assert sanitized == "Start  end"

    # Test that the sanitized text can be encoded to UTF-8 without error
    problematic_text = "Document content \udc00 with \ud800 surrogates \udfff here"
    sanitized = remove_invalid_unicode_chars(problematic_text)
    # This should not raise an exception
    sanitized.encode("utf-8")
    assert sanitized == "Document content  with  surrogates  here"
