export enum VoiceProviderType {
  OPENAI = "openai",
  OPENAI_COMPATIBLE = "openai_compatible",
  AZURE = "azure",
  ELEVENLABS = "elevenlabs",
}

export interface VoiceProviderCustomConfig {
  speech_region?: string;
  stt_languages?: string[];
}

export interface VoiceProviderView {
  id: number;
  name: string;
  provider_type: VoiceProviderType;
  is_default_stt: boolean;
  is_default_tts: boolean;
  stt_model: string | null;
  tts_model: string | null;
  default_voice: string | null;
  /** Masked API key (e.g. `"sk-a...b1c2"`). Non-null means a key is stored. */
  api_key: string | null;
  target_uri: string | null;
  custom_config: VoiceProviderCustomConfig | null;
}

/** A selectable voice option returned by a provider's voices endpoint. */
export interface VoiceOption {
  value: string;
  label: string;
  description?: string;
}

/** Formik form values for the voice provider setup modal. */
export interface VoiceFormValues {
  api_key: string;
  api_base: string;
  target_uri: string;
  stt_model: string;
  tts_model: string;
  default_voice: string;
  /** Comma-separated STT locales (Azure only), e.g. "en-US, fr-FR". */
  stt_languages: string;
}

export interface VoiceProviderTestRequest {
  provider_type: VoiceProviderType;
  api_key?: string | null;
  api_base?: string;
  target_uri?: string;
  use_stored_key?: boolean;
  custom_config?: VoiceProviderCustomConfig;
  stt_model?: string;
}

export interface VoiceProviderUpsertRequest {
  id?: number;
  name: string;
  provider_type: VoiceProviderType;
  api_key?: string | null;
  api_key_changed: boolean;
  llm_provider_id?: number;
  api_base?: string;
  target_uri?: string;
  custom_config?: VoiceProviderCustomConfig;
  stt_model?: string;
  tts_model?: string;
  default_voice?: string;
  activate_stt: boolean;
  activate_tts: boolean;
}
