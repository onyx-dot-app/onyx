export interface VoiceProviderView {
  id: number;
  name: string;
  provider_type: string;
  is_default_stt: boolean;
  is_default_tts: boolean;
  stt_model: string | null;
  tts_model: string | null;
  default_voice: string | null;
  api_key: string | null;
  has_api_key: boolean;
  target_uri: string | null;
}

export interface VoiceOption {
  value: string;
  label: string;
  description?: string;
}

export interface VoiceFormValues {
  api_key: string;
  target_uri: string;
  stt_model: string;
  tts_model: string;
  default_voice: string;
}
