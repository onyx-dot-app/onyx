"""Behavior of the two ciphertext formats and the keyring that reads them.

EE mode is on for this directory, so the `encrypt_string_to_bytes` and
`decrypt_bytes_to_string` wrappers resolve to the EE implementation.
"""

import base64
import json
from collections.abc import Generator
from unittest.mock import patch

import pytest

from ee.onyx.utils.encryption import (
    ENVELOPE_MAGIC,
    ENVELOPE_VERSION,
    LEGACY_KEY_ID,
    CiphertextFormat,
    DecryptionError,
    EncryptionConfigError,
    Keyring,
    UnsupportedCiphertextError,
    build_keyring,
    decrypt_with_keyring,
    describe_keyring,
    encrypt_with_keyring,
    get_keyring,
    is_current_ciphertext,
    parse_envelope_header,
)
from onyx.utils.encryption import (
    decrypt_bytes_to_string,
    encrypt_string_to_bytes,
    validate_encryption_configuration,
)

EE_MODULE = "ee.onyx.utils.encryption"

LEGACY_SECRET = "legacy-secret-value-0123456789ab"
# AES-CBC bytes written by the format that predates envelopes, under
# LEGACY_SECRET, for the plaintext below. Frozen so a change to the legacy
# reader cannot go unnoticed.
LEGACY_VECTOR = bytes.fromhex(
    "000102030405060708090a0b0c0d0e0f"
    "1fdc2e4f8aa06b52c15254de5ef01f906e5e89cc32843e214b5363dfa95cfe2c"
)
LEGACY_VECTOR_PLAINTEXT = '{"api_key": "sk-legacy"}'

KEY_A = base64.b64encode(b"a" * 32).decode()
KEY_B = base64.b64encode(b"b" * 32).decode()


def _keys_json(**keys: str) -> str:
    return json.dumps(keys)


def _legacy_only() -> Keyring:
    return build_keyring(LEGACY_SECRET, "", "")


def _staged(write_key_id: str = "") -> Keyring:
    """Legacy secret plus a new key: phase B when write_key_id is empty, phase C
    when it names the new key."""
    return build_keyring(LEGACY_SECRET, _keys_json(k2026=KEY_A), write_key_id)


def _retired() -> Keyring:
    """Legacy secret removed after rotation."""
    return build_keyring("", _keys_json(k2026=KEY_A), "k2026")


class TestLegacyCompatibility:
    def test_frozen_legacy_vector_decrypts(self) -> None:
        value = decrypt_with_keyring(_legacy_only(), LEGACY_VECTOR)
        assert value.plaintext == LEGACY_VECTOR_PLAINTEXT
        assert value.format == CiphertextFormat.LEGACY_CBC
        assert value.key_id == LEGACY_KEY_ID

    def test_legacy_only_configuration_still_writes_legacy_cbc(self) -> None:
        keyring = _legacy_only()
        data = encrypt_with_keyring(keyring, "hello")
        assert not data.startswith(ENVELOPE_MAGIC)
        assert keyring.write_format == CiphertextFormat.LEGACY_CBC
        assert decrypt_with_keyring(keyring, data).format == CiphertextFormat.LEGACY_CBC

    def test_staged_keys_without_write_key_keep_legacy_writes(self) -> None:
        keyring = _staged()
        assert keyring.write_key_id is None
        data = encrypt_with_keyring(keyring, "hello")
        assert decrypt_with_keyring(_legacy_only(), data).plaintext == "hello"

    def test_no_key_stores_plain_text(self) -> None:
        keyring = build_keyring("", "", "")
        assert encrypt_with_keyring(keyring, "plain") == b"plain"
        value = decrypt_with_keyring(keyring, b"plain")
        assert value.format == CiphertextFormat.PLAINTEXT
        assert value.key_id is None

    def test_plain_text_stored_before_a_key_existed_is_readable(self) -> None:
        value = decrypt_with_keyring(_legacy_only(), b"readable text")
        assert value.plaintext == "readable text"
        assert value.format == CiphertextFormat.PLAINTEXT

    def test_legacy_bytes_under_another_secret_are_unreadable(self) -> None:
        other = build_keyring("another-secret-value-0123456789", "", "")
        with pytest.raises(DecryptionError):
            decrypt_with_keyring(other, LEGACY_VECTOR)

    def test_legacy_secret_is_trimmed_to_an_aes_key_size(self) -> None:
        # 20 bytes trims to 16, so the 16-byte prefix reads the same bytes.
        data = encrypt_with_keyring(build_keyring("f" * 20, "", ""), "data")
        assert (
            decrypt_with_keyring(build_keyring("f" * 16, "", ""), data).plaintext
            == "data"
        )

    def test_legacy_secret_too_short_fails(self) -> None:
        with pytest.raises(EncryptionConfigError, match="too short"):
            build_keyring("short", "", "")


class TestEnvelope:
    def test_round_trip_carries_version_and_key_id(self) -> None:
        keyring = _staged("k2026")
        data = encrypt_with_keyring(keyring, "secret data")
        parsed = parse_envelope_header(data)
        assert parsed is not None
        header, _ = parsed
        assert header.version == ENVELOPE_VERSION
        assert header.key_id == "k2026"
        value = decrypt_with_keyring(keyring, data)
        assert value.plaintext == "secret data"
        assert value.format == CiphertextFormat.ENVELOPE
        assert value.key_id == "k2026"

    def test_each_write_uses_a_fresh_nonce(self) -> None:
        keyring = _staged("k2026")
        assert encrypt_with_keyring(keyring, "same") != encrypt_with_keyring(
            keyring, "same"
        )

    @pytest.mark.parametrize("text", ["", "日本語テスト 🔐 émojis", "x" * 10_000])
    def test_round_trip_edge_texts(self, text: str) -> None:
        keyring = _staged("k2026")
        assert (
            decrypt_with_keyring(keyring, encrypt_with_keyring(keyring, text)).plaintext
            == text
        )

    def test_legacy_secret_can_write_envelopes_under_a_derived_key(self) -> None:
        keyring = build_keyring(LEGACY_SECRET, "", LEGACY_KEY_ID)
        data = encrypt_with_keyring(keyring, "same secret")
        parsed = parse_envelope_header(data)
        assert parsed is not None
        assert parsed[0].key_id == LEGACY_KEY_ID
        assert is_current_ciphertext(keyring, data)
        assert decrypt_with_keyring(_legacy_only(), data).plaintext == "same secret"
        # The AES-CBC key bytes themselves never serve AES-GCM.
        assert keyring.legacy_key is not None
        assert keyring.keys[LEGACY_KEY_ID] != keyring.legacy_key
        assert len(keyring.keys[LEGACY_KEY_ID]) == 32

    def test_is_current_only_for_the_write_key(self) -> None:
        under_a = encrypt_with_keyring(_staged("k2026"), "v")
        assert is_current_ciphertext(_staged("k2026"), under_a)
        assert not is_current_ciphertext(_staged(), under_a)
        assert not is_current_ciphertext(_staged("k2026"), LEGACY_VECTOR)
        two_keys = build_keyring("", _keys_json(k2026=KEY_A, k2027=KEY_B), "k2027")
        assert not is_current_ciphertext(two_keys, under_a)


class TestMixedPhases:
    def test_envelope_reader_reads_legacy_writer_output(self) -> None:
        data = encrypt_with_keyring(_legacy_only(), "from an old pod")
        assert (
            decrypt_with_keyring(_staged("k2026"), data).plaintext == "from an old pod"
        )

    def test_staged_reader_reads_envelope_writer_output(self) -> None:
        data = encrypt_with_keyring(_staged("k2026"), "from a new pod")
        assert decrypt_with_keyring(_staged(), data).plaintext == "from a new pod"

    def test_retired_legacy_key_cannot_read_legacy_bytes(self) -> None:
        with pytest.raises(DecryptionError):
            decrypt_with_keyring(_retired(), LEGACY_VECTOR)

    def test_old_envelope_key_stays_readable_after_a_second_rotation(self) -> None:
        data = encrypt_with_keyring(_retired(), "under k2026")
        next_keyring = build_keyring("", _keys_json(k2026=KEY_A, k2027=KEY_B), "k2027")
        assert decrypt_with_keyring(next_keyring, data).plaintext == "under k2026"
        assert not is_current_ciphertext(next_keyring, data)


class TestFailsSafely:
    def test_tampered_body_fails_authentication(self) -> None:
        keyring = _staged("k2026")
        data = bytearray(encrypt_with_keyring(keyring, "payload"))
        data[-1] ^= 0x01
        with pytest.raises(DecryptionError, match="authentication"):
            decrypt_with_keyring(keyring, bytes(data))

    def test_tampered_header_fails_authentication(self) -> None:
        keyring = build_keyring("", _keys_json(k2026=KEY_A, k2027=KEY_A), "k2026")
        data = encrypt_with_keyring(keyring, "payload")
        # Same key material under another id: only the authenticated header differs.
        swapped = data.replace(b"k2026", b"k2027", 1)
        with pytest.raises(DecryptionError, match="authentication"):
            decrypt_with_keyring(keyring, swapped)

    def test_unknown_key_id_is_unsupported(self) -> None:
        data = encrypt_with_keyring(_staged("k2026"), "payload")
        with pytest.raises(UnsupportedCiphertextError, match="k2026"):
            decrypt_with_keyring(_legacy_only(), data)

    def test_unknown_version_is_unsupported(self) -> None:
        keyring = _staged("k2026")
        data = bytearray(encrypt_with_keyring(keyring, "payload"))
        data[len(ENVELOPE_MAGIC)] = ENVELOPE_VERSION + 1
        with pytest.raises(UnsupportedCiphertextError, match="version"):
            decrypt_with_keyring(keyring, bytes(data))

    @pytest.mark.parametrize(
        "data",
        [
            ENVELOPE_MAGIC,
            ENVELOPE_MAGIC + bytes([ENVELOPE_VERSION]),
            ENVELOPE_MAGIC + bytes([ENVELOPE_VERSION, 0]) + b"\x00" * 40,
            ENVELOPE_MAGIC + bytes([ENVELOPE_VERSION, 3]) + b"k 1" + b"\x00" * 40,
            ENVELOPE_MAGIC + bytes([ENVELOPE_VERSION, 5]) + b"k2026" + b"\x00" * 10,
        ],
        ids=["magic-only", "no-key-length", "empty-key-id", "bad-key-id", "too-short"],
    )
    def test_malformed_envelope_never_reads_as_legacy(
        self, data: bytes, caplog: pytest.LogCaptureFixture
    ) -> None:
        # The message names the envelope: the legacy reader was never tried.
        with pytest.raises(DecryptionError, match="^Envelope"):
            decrypt_with_keyring(_staged("k2026"), data)
        with pytest.raises(DecryptionError, match="^Envelope"):
            parse_envelope_header(data)
        assert "reading it as plain text" not in caplog.text

    def test_authentication_failure_is_not_read_as_plain_text(self) -> None:
        keyring = _staged("k2026")
        header_and_nonce = encrypt_with_keyring(keyring, "x")[: 7 + 5 + 12]
        forged = header_and_nonce + b"plain text that is valid UTF-8!!"
        with pytest.raises(DecryptionError, match="authentication"):
            decrypt_with_keyring(keyring, forged)

    def test_tampered_key_id_length_is_not_read_under_another_id(self) -> None:
        keyring = build_keyring("", _keys_json(k202=KEY_A, k2026=KEY_A), "k2026")
        data = bytearray(encrypt_with_keyring(keyring, "payload"))
        data[len(ENVELOPE_MAGIC) + 1] -= 1
        # Same key material under the shorter id: only the authenticated header differs.
        with pytest.raises(DecryptionError, match="authentication"):
            decrypt_with_keyring(keyring, bytes(data))

    def test_truncated_body_fails_authentication(self) -> None:
        keyring = _staged("k2026")
        data = encrypt_with_keyring(keyring, "payload that is long enough")
        with pytest.raises(DecryptionError, match="authentication"):
            decrypt_with_keyring(keyring, data[:-1])

    def test_legacy_envelope_is_unsupported_once_the_secret_is_retired(self) -> None:
        data = encrypt_with_keyring(
            build_keyring(LEGACY_SECRET, "", LEGACY_KEY_ID), "p"
        )
        with pytest.raises(UnsupportedCiphertextError, match="'legacy'"):
            decrypt_with_keyring(_retired(), data)

    def test_plain_text_fallback_logs_a_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level("WARNING"):
            decrypt_with_keyring(_legacy_only(), b"readable text")
        assert "reading it as plain text" in caplog.text

    def test_random_bytes_are_unreadable(self) -> None:
        with pytest.raises(DecryptionError, match="not UTF-8"):
            decrypt_with_keyring(_staged("k2026"), b"\x80\x81\x82\x83" * 8)

    def test_error_messages_carry_no_key_material(self) -> None:
        with pytest.raises(UnsupportedCiphertextError) as info:
            decrypt_with_keyring(
                _legacy_only(), encrypt_with_keyring(_staged("k2026"), "p")
            )
        assert LEGACY_SECRET not in str(info.value)
        assert KEY_A not in str(info.value)


class TestKeyringConfiguration:
    @pytest.mark.parametrize(
        ("keys_json", "match"),
        [
            ("not json", "not valid JSON"),
            ('["k"]', "JSON object"),
            ('{"bad id!": "%s"}' % KEY_A, "key id #1 must match"),
            ('{"": "%s"}' % KEY_A, "key id #1 must match"),
            ('{"%s": "%s"}' % ("x" * 33, KEY_A), "key id #1 must match"),
            ('{"legacy": "%s"}' % KEY_A, "reserved"),
            ('{"k": 5}', "base64 string"),
            ('{"k": "not*base64"}', "not standard base64"),
            ('{"k": "%s"}' % base64.b64encode(b"a" * 16).decode(), "16 bytes, not 32"),
            ('{"k": "%s", "k": "%s"}' % (KEY_A, KEY_B), "more than once"),
        ],
    )
    def test_invalid_keys_json(self, keys_json: str, match: str) -> None:
        with pytest.raises(EncryptionConfigError, match=match):
            build_keyring("", keys_json, "")

    @pytest.mark.parametrize(
        ("keys_json", "write_key_id"),
        [
            ('{"%s": "k2026"}' % KEY_A, ""),
            ('{"%s": "a", "%s": "b"}' % (KEY_A, KEY_A), ""),
            (_keys_json(k2026=KEY_A), KEY_A),
        ],
        ids=["key-as-id", "duplicate-key-as-id", "key-as-write-id"],
    )
    def test_key_material_in_an_id_setting_is_not_echoed(
        self, keys_json: str, write_key_id: str
    ) -> None:
        with pytest.raises(EncryptionConfigError) as info:
            build_keyring("", keys_json, write_key_id)
        assert KEY_A not in str(info.value)

    def test_write_key_must_be_configured(self) -> None:
        with pytest.raises(EncryptionConfigError, match="not in ENCRYPTION_KEYS"):
            build_keyring("", _keys_json(k2026=KEY_A), "k2027")
        with pytest.raises(EncryptionConfigError, match="not in ENCRYPTION_KEYS"):
            build_keyring("", "", "k2026")

    def test_legacy_write_key_needs_the_legacy_secret(self) -> None:
        with pytest.raises(EncryptionConfigError, match="needs ENCRYPTION_KEY_SECRET"):
            build_keyring("", _keys_json(k2026=KEY_A), LEGACY_KEY_ID)

    def test_readable_ids_include_legacy_only_when_the_secret_is_set(self) -> None:
        assert sorted(_staged().keys) == ["k2026", LEGACY_KEY_ID]
        assert sorted(_retired().keys) == ["k2026"]

    def test_description_names_ids_and_write_mode_only(self) -> None:
        text = describe_keyring(_staged("k2026"))
        assert "k2026" in text and "legacy" in text
        assert LEGACY_SECRET not in text and KEY_A not in text
        assert describe_keyring(_legacy_only()).endswith("writes legacy_cbc")
        assert describe_keyring(build_keyring("", "", "")).endswith("writes plaintext")


class TestProcessEntryPoints:
    """The versioned wrappers and the startup check use the process keyring."""

    def test_wrappers_round_trip_through_the_process_keyring(self) -> None:
        with patch(f"{EE_MODULE}.get_keyring", return_value=_staged("k2026")):
            data = encrypt_string_to_bytes("payload")
            assert data.startswith(ENVELOPE_MAGIC)
            assert decrypt_bytes_to_string(data) == "payload"

    @pytest.fixture
    def process_settings(self) -> Generator[None, None, None]:
        """The real loader, reading patched settings instead of the cached ones."""
        get_keyring.cache_clear()
        with (
            patch(f"{EE_MODULE}.ENCRYPTION_KEY_SECRET", LEGACY_SECRET),
            patch(f"{EE_MODULE}.ENCRYPTION_KEYS_JSON", "{"),
            patch(f"{EE_MODULE}.ENCRYPTION_WRITE_KEY_ID", ""),
        ):
            yield
        get_keyring.cache_clear()

    @pytest.mark.usefixtures("process_settings")
    def test_startup_validation_rejects_bad_configuration(self) -> None:
        with pytest.raises(EncryptionConfigError, match="not valid JSON"):
            validate_encryption_configuration()
        with pytest.raises(EncryptionConfigError, match="not valid JSON"):
            encrypt_string_to_bytes("payload")

    def test_startup_validation_passes_and_logs_ids_only(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with (
            patch(f"{EE_MODULE}.get_keyring", return_value=_staged("k2026")),
            caplog.at_level("INFO"),
        ):
            validate_encryption_configuration()
        assert "k2026" in caplog.text
        assert LEGACY_SECRET not in caplog.text and KEY_A not in caplog.text
