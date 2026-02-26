"use client";

import { useState } from "react";
import Modal from "@/refresh-components/Modal";
import Button from "@/refresh-components/buttons/Button";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { Vertical, Horizontal } from "@/layouts/input-layouts";
import { toast } from "@/hooks/useToast";
import { Section } from "@/layouts/general-layouts";
import { SvgSettings } from "@opal/icons";

interface VoiceProviderView {
  id: number;
  name: string;
  provider_type: string;
  is_default_stt: boolean;
  is_default_tts: boolean;
  stt_model: string | null;
  tts_model: string | null;
  default_voice: string | null;
  has_api_key: boolean;
}

interface VoiceProviderSetupModalProps {
  providerType: string;
  existingProvider: VoiceProviderView | null;
  mode: "stt" | "tts";
  onClose: () => void;
  onSuccess: () => void;
}

const PROVIDER_LABELS: Record<string, string> = {
  openai: "OpenAI",
  azure: "Azure Speech Services",
  elevenlabs: "ElevenLabs",
};

const OPENAI_VOICES = [
  { id: "alloy", name: "Alloy" },
  { id: "echo", name: "Echo" },
  { id: "nova", name: "Nova" },
  { id: "onyx", name: "Onyx" },
  { id: "shimmer", name: "Shimmer" },
];

const OPENAI_STT_MODELS = [{ id: "whisper-1", name: "Whisper v1" }];

const OPENAI_TTS_MODELS = [
  { id: "tts-1", name: "TTS-1 (Standard)" },
  { id: "tts-1-hd", name: "TTS-1 HD (High Quality)" },
];

const ELEVENLABS_VOICES = [
  { id: "rachel", name: "Rachel" },
  { id: "josh", name: "Josh" },
  { id: "bella", name: "Bella" },
  { id: "adam", name: "Adam" },
  { id: "elli", name: "Elli" },
];

const AZURE_VOICES = [
  { id: "en-US-JennyNeural", name: "Jenny (Female)" },
  { id: "en-US-GuyNeural", name: "Guy (Male)" },
  { id: "en-US-AriaNeural", name: "Aria (Female)" },
  { id: "en-US-DavisNeural", name: "Davis (Male)" },
  { id: "en-US-EmmaNeural", name: "Emma (Female)" },
];

export default function VoiceProviderSetupModal({
  providerType,
  existingProvider,
  mode,
  onClose,
  onSuccess,
}: VoiceProviderSetupModalProps) {
  const [apiKey, setApiKey] = useState("");
  const [apiKeyChanged, setApiKeyChanged] = useState(false);
  const [sttModel, setSttModel] = useState(
    existingProvider?.stt_model ?? "whisper-1"
  );
  const [ttsModel, setTtsModel] = useState(
    existingProvider?.tts_model ?? "tts-1"
  );
  const getDefaultVoice = () => {
    if (existingProvider?.default_voice) return existingProvider.default_voice;
    if (providerType === "elevenlabs") return "rachel";
    if (providerType === "azure") return "en-US-JennyNeural";
    return "alloy"; // OpenAI default
  };
  const [defaultVoice, setDefaultVoice] = useState(getDefaultVoice());
  const [isSubmitting, setIsSubmitting] = useState(false);

  const isEditing = !!existingProvider;
  const label = PROVIDER_LABELS[providerType] ?? providerType;
  const modeLabel = mode === "stt" ? "Speech-to-Text" : "Text-to-Speech";

  const handleSubmit = async () => {
    if (!isEditing && !apiKey) {
      toast.error("API key is required");
      return;
    }

    setIsSubmitting(true);
    try {
      // Test the connection first
      const testResponse = await fetch("/api/admin/voice/providers/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider_type: providerType,
          api_key: apiKeyChanged ? apiKey : undefined,
          use_stored_key: isEditing && !apiKeyChanged,
        }),
      });

      if (!testResponse.ok) {
        const data = await testResponse.json();
        toast.error(data.detail || "Connection test failed");
        setIsSubmitting(false);
        return;
      }

      // If test passed, save the provider
      const response = await fetch("/api/admin/voice/providers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: existingProvider?.id,
          name: label,
          provider_type: providerType,
          api_key: apiKeyChanged ? apiKey : undefined,
          api_key_changed: apiKeyChanged,
          stt_model: sttModel,
          tts_model: ttsModel,
          default_voice: defaultVoice,
          activate_stt: mode === "stt",
          activate_tts: mode === "tts",
        }),
      });

      if (response.ok) {
        toast.success(isEditing ? "Provider updated" : "Provider connected");
        onSuccess();
      } else {
        const data = await response.json();
        toast.error(data.detail || "Failed to save provider");
      }
    } catch {
      toast.error("Failed to save provider");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Modal open onOpenChange={(isOpen) => !isOpen && onClose()}>
      <Modal.Content width="sm">
        <Modal.Header
          icon={SvgSettings}
          title={isEditing ? `Edit ${label}` : `Connect ${label}`}
          description={`Configure ${modeLabel} settings`}
          onClose={onClose}
        />
        <Modal.Body>
          <Section gap={1} alignItems="stretch">
            <Vertical
              title="API Key"
              description={
                isEditing
                  ? "Leave blank to keep existing key"
                  : "Enter your API key"
              }
              nonInteractive
            >
              <InputTypeIn
                type="password"
                placeholder={isEditing ? "••••••••" : "Enter API key"}
                value={apiKey}
                onChange={(e) => {
                  setApiKey(e.target.value);
                  setApiKeyChanged(true);
                }}
              />
            </Vertical>

            {providerType === "openai" && mode === "stt" && (
              <Horizontal title="STT Model" center nonInteractive>
                <InputSelect value={sttModel} onValueChange={setSttModel}>
                  <InputSelect.Trigger />
                  <InputSelect.Content>
                    {OPENAI_STT_MODELS.map((model) => (
                      <InputSelect.Item key={model.id} value={model.id}>
                        {model.name}
                      </InputSelect.Item>
                    ))}
                  </InputSelect.Content>
                </InputSelect>
              </Horizontal>
            )}

            {providerType === "openai" && mode === "tts" && (
              <>
                <Horizontal title="TTS Model" center nonInteractive>
                  <InputSelect value={ttsModel} onValueChange={setTtsModel}>
                    <InputSelect.Trigger />
                    <InputSelect.Content>
                      {OPENAI_TTS_MODELS.map((model) => (
                        <InputSelect.Item key={model.id} value={model.id}>
                          {model.name}
                        </InputSelect.Item>
                      ))}
                    </InputSelect.Content>
                  </InputSelect>
                </Horizontal>

                <Horizontal title="Default Voice" center nonInteractive>
                  <InputSelect
                    value={defaultVoice}
                    onValueChange={setDefaultVoice}
                  >
                    <InputSelect.Trigger />
                    <InputSelect.Content>
                      {OPENAI_VOICES.map((voice) => (
                        <InputSelect.Item key={voice.id} value={voice.id}>
                          {voice.name}
                        </InputSelect.Item>
                      ))}
                    </InputSelect.Content>
                  </InputSelect>
                </Horizontal>
              </>
            )}

            {providerType === "elevenlabs" && mode === "tts" && (
              <Horizontal title="Default Voice" center nonInteractive>
                <InputSelect
                  value={defaultVoice}
                  onValueChange={setDefaultVoice}
                >
                  <InputSelect.Trigger />
                  <InputSelect.Content>
                    {ELEVENLABS_VOICES.map((voice) => (
                      <InputSelect.Item key={voice.id} value={voice.id}>
                        {voice.name}
                      </InputSelect.Item>
                    ))}
                  </InputSelect.Content>
                </InputSelect>
              </Horizontal>
            )}

            {providerType === "azure" && mode === "tts" && (
              <Horizontal title="Default Voice" center nonInteractive>
                <InputSelect
                  value={defaultVoice}
                  onValueChange={setDefaultVoice}
                >
                  <InputSelect.Trigger />
                  <InputSelect.Content>
                    {AZURE_VOICES.map((voice) => (
                      <InputSelect.Item key={voice.id} value={voice.id}>
                        {voice.name}
                      </InputSelect.Item>
                    ))}
                  </InputSelect.Content>
                </InputSelect>
              </Horizontal>
            )}
          </Section>
        </Modal.Body>
        <Modal.Footer>
          <Button secondary onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={isSubmitting}>
            {isSubmitting ? "Connecting..." : isEditing ? "Save" : "Connect"}
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
