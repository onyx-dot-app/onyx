"""Unit tests for onyx.db.voice module."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from onyx.db.models import VoiceProvider
from onyx.db.voice import deactivate_stt_provider
from onyx.db.voice import deactivate_tts_provider
from onyx.db.voice import delete_voice_provider
from onyx.db.voice import fetch_default_stt_provider
from onyx.db.voice import fetch_default_tts_provider
from onyx.db.voice import fetch_voice_provider_by_id
from onyx.db.voice import fetch_voice_provider_by_type
from onyx.db.voice import fetch_voice_providers
from onyx.db.voice import MAX_VOICE_PLAYBACK_SPEED
from onyx.db.voice import MIN_VOICE_PLAYBACK_SPEED
from onyx.db.voice import set_default_stt_provider
from onyx.db.voice import set_default_tts_provider
from onyx.db.voice import update_user_voice_settings
from onyx.db.voice import upsert_voice_provider
from onyx.error_handling.exceptions import OnyxError


def _make_voice_provider(
    id: int = 1,
    name: str = "Test Provider",
    provider_type: str = "openai",
    is_default_stt: bool = False,
    is_default_tts: bool = False,
) -> VoiceProvider:
    """Create a VoiceProvider instance for testing."""
    provider = VoiceProvider()
    provider.id = id
    provider.name = name
    provider.provider_type = provider_type
    provider.is_default_stt = is_default_stt
    provider.is_default_tts = is_default_tts
    provider.api_key = None
    provider.api_base = None
    provider.custom_config = None
    provider.stt_model = None
    provider.tts_model = None
    provider.default_voice = None
    return provider


class TestFetchVoiceProviders:
    """Tests for fetch_voice_providers."""

    def test_returns_all_providers(self, mock_db_session: MagicMock) -> None:
        providers = [
            _make_voice_provider(id=1, name="Provider A"),
            _make_voice_provider(id=2, name="Provider B"),
        ]
        mock_db_session.scalars.return_value.all.return_value = providers

        result = fetch_voice_providers(mock_db_session)

        assert result == providers
        mock_db_session.scalars.assert_called_once()

    def test_returns_empty_list_when_no_providers(
        self, mock_db_session: MagicMock
    ) -> None:
        mock_db_session.scalars.return_value.all.return_value = []

        result = fetch_voice_providers(mock_db_session)

        assert result == []


class TestFetchVoiceProviderById:
    """Tests for fetch_voice_provider_by_id."""

    def test_returns_provider_when_found(self, mock_db_session: MagicMock) -> None:
        provider = _make_voice_provider(id=1)
        mock_db_session.scalar.return_value = provider

        result = fetch_voice_provider_by_id(mock_db_session, 1)

        assert result is provider
        mock_db_session.scalar.assert_called_once()

    def test_returns_none_when_not_found(self, mock_db_session: MagicMock) -> None:
        mock_db_session.scalar.return_value = None

        result = fetch_voice_provider_by_id(mock_db_session, 999)

        assert result is None


class TestFetchDefaultProviders:
    """Tests for fetch_default_stt_provider and fetch_default_tts_provider."""

    def test_fetch_default_stt_provider_returns_provider(
        self, mock_db_session: MagicMock
    ) -> None:
        provider = _make_voice_provider(id=1, is_default_stt=True)
        mock_db_session.scalar.return_value = provider

        result = fetch_default_stt_provider(mock_db_session)

        assert result is provider

    def test_fetch_default_stt_provider_returns_none_when_no_default(
        self, mock_db_session: MagicMock
    ) -> None:
        mock_db_session.scalar.return_value = None

        result = fetch_default_stt_provider(mock_db_session)

        assert result is None

    def test_fetch_default_tts_provider_returns_provider(
        self, mock_db_session: MagicMock
    ) -> None:
        provider = _make_voice_provider(id=1, is_default_tts=True)
        mock_db_session.scalar.return_value = provider

        result = fetch_default_tts_provider(mock_db_session)

        assert result is provider

    def test_fetch_default_tts_provider_returns_none_when_no_default(
        self, mock_db_session: MagicMock
    ) -> None:
        mock_db_session.scalar.return_value = None

        result = fetch_default_tts_provider(mock_db_session)

        assert result is None


class TestFetchVoiceProviderByType:
    """Tests for fetch_voice_provider_by_type."""

    def test_returns_provider_when_found(self, mock_db_session: MagicMock) -> None:
        provider = _make_voice_provider(id=1, provider_type="openai")
        mock_db_session.scalar.return_value = provider

        result = fetch_voice_provider_by_type(mock_db_session, "openai")

        assert result is provider

    def test_returns_none_when_not_found(self, mock_db_session: MagicMock) -> None:
        mock_db_session.scalar.return_value = None

        result = fetch_voice_provider_by_type(mock_db_session, "nonexistent")

        assert result is None


class TestUpsertVoiceProvider:
    """Tests for upsert_voice_provider."""

    def test_creates_new_provider_when_no_id(self, mock_db_session: MagicMock) -> None:
        mock_db_session.flush.return_value = None
        mock_db_session.refresh.return_value = None

        upsert_voice_provider(
            db_session=mock_db_session,
            provider_id=None,
            name="New Provider",
            provider_type="openai",
            api_key="test-key",
            api_key_changed=True,
        )

        mock_db_session.add.assert_called_once()
        mock_db_session.flush.assert_called()
        added_obj = mock_db_session.add.call_args[0][0]
        assert added_obj.name == "New Provider"
        assert added_obj.provider_type == "openai"

    def test_updates_existing_provider(self, mock_db_session: MagicMock) -> None:
        existing_provider = _make_voice_provider(id=1, name="Old Name")
        mock_db_session.scalar.return_value = existing_provider
        mock_db_session.flush.return_value = None
        mock_db_session.refresh.return_value = None

        upsert_voice_provider(
            db_session=mock_db_session,
            provider_id=1,
            name="Updated Name",
            provider_type="elevenlabs",
            api_key="new-key",
            api_key_changed=True,
        )

        mock_db_session.add.assert_not_called()
        assert existing_provider.name == "Updated Name"
        assert existing_provider.provider_type == "elevenlabs"

    def test_raises_when_provider_not_found(self, mock_db_session: MagicMock) -> None:
        mock_db_session.scalar.return_value = None

        with pytest.raises(OnyxError) as exc_info:
            upsert_voice_provider(
                db_session=mock_db_session,
                provider_id=999,
                name="Test",
                provider_type="openai",
                api_key=None,
                api_key_changed=False,
            )

        assert "No voice provider with id 999" in str(exc_info.value)

    def test_does_not_update_api_key_when_not_changed(
        self, mock_db_session: MagicMock
    ) -> None:
        existing_provider = _make_voice_provider(id=1)
        existing_provider.api_key = "original-key"  # ty: ignore[invalid-assignment]
        original_api_key = existing_provider.api_key
        mock_db_session.scalar.return_value = existing_provider
        mock_db_session.flush.return_value = None
        mock_db_session.refresh.return_value = None

        upsert_voice_provider(
            db_session=mock_db_session,
            provider_id=1,
            name="Test",
            provider_type="openai",
            api_key="new-key",
            api_key_changed=False,
        )

        # api_key should remain unchanged (same object reference)
        assert existing_provider.api_key is original_api_key

    def test_activates_stt_when_requested(self, mock_db_session: MagicMock) -> None:
        existing_provider = _make_voice_provider(id=1)
        mock_db_session.scalar.return_value = existing_provider
        mock_db_session.flush.return_value = None
        mock_db_session.refresh.return_value = None
        mock_db_session.execute.return_value = None

        upsert_voice_provider(
            db_session=mock_db_session,
            provider_id=1,
            name="Test",
            provider_type="openai",
            api_key=None,
            api_key_changed=False,
            activate_stt=True,
        )

        assert existing_provider.is_default_stt is True

    def test_activates_tts_when_requested(self, mock_db_session: MagicMock) -> None:
        existing_provider = _make_voice_provider(id=1)
        mock_db_session.scalar.return_value = existing_provider
        mock_db_session.flush.return_value = None
        mock_db_session.refresh.return_value = None
        mock_db_session.execute.return_value = None

        upsert_voice_provider(
            db_session=mock_db_session,
            provider_id=1,
            name="Test",
            provider_type="openai",
            api_key=None,
            api_key_changed=False,
            activate_tts=True,
        )

        assert existing_provider.is_default_tts is True


class TestDeleteVoiceProvider:
    """Tests for delete_voice_provider."""

    def test_hard_deletes_provider_when_found(self, mock_db_session: MagicMock) -> None:
        provider = _make_voice_provider(id=1)
        mock_db_session.scalar.return_value = provider

        delete_voice_provider(mock_db_session, 1)

        mock_db_session.delete.assert_called_once_with(provider)
        mock_db_session.flush.assert_called_once()

    def test_does_nothing_when_provider_not_found(
        self, mock_db_session: MagicMock
    ) -> None:
        mock_db_session.scalar.return_value = None

        delete_voice_provider(mock_db_session, 999)

        mock_db_session.flush.assert_not_called()


class TestSetDefaultProviders:
    """Tests for set_default_stt_provider and set_default_tts_provider."""

    def test_set_default_stt_provider_deactivates_others(
        self, mock_db_session: MagicMock
    ) -> None:
        provider = _make_voice_provider(id=1)
        mock_db_session.scalar.return_value = provider
        mock_db_session.execute.return_value = None
        mock_db_session.flush.return_value = None
        mock_db_session.refresh.return_value = None

        result = set_default_stt_provider(db_session=mock_db_session, provider_id=1)

        mock_db_session.execute.assert_called_once()
        assert result.is_default_stt is True

    def test_set_default_stt_provider_raises_when_not_found(
        self, mock_db_session: MagicMock
    ) -> None:
        mock_db_session.scalar.return_value = None

        with pytest.raises(OnyxError) as exc_info:
            set_default_stt_provider(db_session=mock_db_session, provider_id=999)

        assert "No voice provider with id 999" in str(exc_info.value)

    def test_set_default_tts_provider_deactivates_others(
        self, mock_db_session: MagicMock
    ) -> None:
        provider = _make_voice_provider(id=1)
        mock_db_session.scalar.return_value = provider
        mock_db_session.execute.return_value = None
        mock_db_session.flush.return_value = None
        mock_db_session.refresh.return_value = None

        result = set_default_tts_provider(db_session=mock_db_session, provider_id=1)

        mock_db_session.execute.assert_called_once()
        assert result.is_default_tts is True

    def test_set_default_tts_provider_updates_model_when_provided(
        self, mock_db_session: MagicMock
    ) -> None:
        provider = _make_voice_provider(id=1)
        mock_db_session.scalar.return_value = provider
        mock_db_session.execute.return_value = None
        mock_db_session.flush.return_value = None
        mock_db_session.refresh.return_value = None

        result = set_default_tts_provider(
            db_session=mock_db_session, provider_id=1, tts_model="tts-1-hd"
        )

        assert result.tts_model == "tts-1-hd"

    def test_set_default_tts_provider_raises_when_not_found(
        self, mock_db_session: MagicMock
    ) -> None:
        mock_db_session.scalar.return_value = None

        with pytest.raises(OnyxError) as exc_info:
            set_default_tts_provider(db_session=mock_db_session, provider_id=999)

        assert "No voice provider with id 999" in str(exc_info.value)


class TestDeactivateProviders:
    """Tests for deactivate_stt_provider and deactivate_tts_provider."""

    def test_deactivate_stt_provider_sets_false(
        self, mock_db_session: MagicMock
    ) -> None:
        provider = _make_voice_provider(id=1, is_default_stt=True)
        mock_db_session.scalar.return_value = provider
        mock_db_session.flush.return_value = None
        mock_db_session.refresh.return_value = None

        result = deactivate_stt_provider(db_session=mock_db_session, provider_id=1)

        assert result.is_default_stt is False

    def test_deactivate_stt_provider_raises_when_not_found(
        self, mock_db_session: MagicMock
    ) -> None:
        mock_db_session.scalar.return_value = None

        with pytest.raises(OnyxError) as exc_info:
            deactivate_stt_provider(db_session=mock_db_session, provider_id=999)

        assert "No voice provider with id 999" in str(exc_info.value)

    def test_deactivate_tts_provider_sets_false(
        self, mock_db_session: MagicMock
    ) -> None:
        provider = _make_voice_provider(id=1, is_default_tts=True)
        mock_db_session.scalar.return_value = provider
        mock_db_session.flush.return_value = None
        mock_db_session.refresh.return_value = None

        result = deactivate_tts_provider(db_session=mock_db_session, provider_id=1)

        assert result.is_default_tts is False

    def test_deactivate_tts_provider_raises_when_not_found(
        self, mock_db_session: MagicMock
    ) -> None:
        mock_db_session.scalar.return_value = None

        with pytest.raises(OnyxError) as exc_info:
            deactivate_tts_provider(db_session=mock_db_session, provider_id=999)

        assert "No voice provider with id 999" in str(exc_info.value)


class TestUpdateUserVoiceSettings:
    """Tests for update_user_voice_settings."""

    def test_updates_auto_send(self, mock_db_session: MagicMock) -> None:
        user_id = uuid4()

        update_user_voice_settings(mock_db_session, user_id, auto_send=True)

        mock_db_session.execute.assert_called_once()
        mock_db_session.flush.assert_called_once()

    def test_updates_auto_playback(self, mock_db_session: MagicMock) -> None:
        user_id = uuid4()

        update_user_voice_settings(mock_db_session, user_id, auto_playback=True)

        mock_db_session.execute.assert_called_once()
        mock_db_session.flush.assert_called_once()

    def test_updates_playback_speed_within_range(
        self, mock_db_session: MagicMock
    ) -> None:
        user_id = uuid4()

        update_user_voice_settings(mock_db_session, user_id, playback_speed=1.5)

        mock_db_session.execute.assert_called_once()

    def test_clamps_playback_speed_to_min(self, mock_db_session: MagicMock) -> None:
        user_id = uuid4()

        update_user_voice_settings(mock_db_session, user_id, playback_speed=0.1)

        mock_db_session.execute.assert_called_once()
        stmt = mock_db_session.execute.call_args[0][0]
        compiled = stmt.compile(compile_kwargs={"literal_binds": True})
        assert str(MIN_VOICE_PLAYBACK_SPEED) in str(compiled)

    def test_clamps_playback_speed_to_max(self, mock_db_session: MagicMock) -> None:
        user_id = uuid4()

        update_user_voice_settings(mock_db_session, user_id, playback_speed=5.0)

        mock_db_session.execute.assert_called_once()
        stmt = mock_db_session.execute.call_args[0][0]
        compiled = stmt.compile(compile_kwargs={"literal_binds": True})
        assert str(MAX_VOICE_PLAYBACK_SPEED) in str(compiled)

    def test_updates_multiple_settings(self, mock_db_session: MagicMock) -> None:
        user_id = uuid4()

        update_user_voice_settings(
            mock_db_session,
            user_id,
            auto_send=True,
            auto_playback=False,
            playback_speed=1.25,
        )

        mock_db_session.execute.assert_called_once()
        mock_db_session.flush.assert_called_once()

    def test_does_nothing_when_no_settings_provided(
        self, mock_db_session: MagicMock
    ) -> None:
        user_id = uuid4()

        update_user_voice_settings(mock_db_session, user_id)

        mock_db_session.execute.assert_not_called()
        mock_db_session.flush.assert_not_called()


class TestSpeedClampingLogic:
    """Tests for the speed clamping constants and logic."""

    def test_min_speed_constant(self) -> None:
        assert MIN_VOICE_PLAYBACK_SPEED == 0.5

    def test_max_speed_constant(self) -> None:
        assert MAX_VOICE_PLAYBACK_SPEED == 2.0

    def test_clamping_formula(self) -> None:
        """Verify the clamping formula used in update_user_voice_settings."""
        test_cases = [
            (0.1, MIN_VOICE_PLAYBACK_SPEED),
            (0.5, 0.5),
            (1.0, 1.0),
            (1.5, 1.5),
            (2.0, 2.0),
            (3.0, MAX_VOICE_PLAYBACK_SPEED),
        ]
        for speed, expected in test_cases:
            clamped = max(
                MIN_VOICE_PLAYBACK_SPEED, min(MAX_VOICE_PLAYBACK_SPEED, speed)
            )
            assert (
                clamped == expected
            ), f"speed={speed} expected={expected} got={clamped}"
