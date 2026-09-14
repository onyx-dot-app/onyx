import {
  hasVoiceProviderAlternative,
  isVoiceProviderConfigured,
} from "@/lib/voice/utils";
import { VoiceProviderType, type VoiceProviderView } from "@/lib/voice/types";

const compatibleProvider: VoiceProviderView = {
  id: 41,
  name: "OpenAI-Compatible",
  provider_type: VoiceProviderType.OPENAI_COMPATIBLE,
  is_default_stt: false,
  is_default_tts: false,
  stt_model: "whisper-large-v3",
  tts_model: null,
  default_voice: null,
  api_key: null,
  target_uri: "https://stt.example/v1",
  custom_config: null,
};

test("OpenAI-compatible STT is configured but is not a TTS alternative", () => {
  expect(isVoiceProviderConfigured(compatibleProvider)).toBe(true);
  expect(
    hasVoiceProviderAlternative(
      [compatibleProvider],
      VoiceProviderType.OPENAI,
      "stt"
    )
  ).toBe(true);
  expect(
    hasVoiceProviderAlternative(
      [compatibleProvider],
      VoiceProviderType.OPENAI,
      "tts"
    )
  ).toBe(false);
});
