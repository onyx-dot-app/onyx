/** Shape of a voice provider returned by the admin API. */
export interface VoiceProviderView {
  id: number;
  name: string;
  provider_type: string;
  is_default_stt: boolean;
  is_default_tts: boolean;
  stt_model: string | null;
  tts_model: string | null;
  default_voice: string | null;
  /** Masked API key (e.g. `"sk-a...b1c2"`). Non-null means a key is stored. */
  api_key: string | null;
  target_uri: string | null;
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
  target_uri: string;
  stt_model: string;
  tts_model: string;
  default_voice: string;
}
