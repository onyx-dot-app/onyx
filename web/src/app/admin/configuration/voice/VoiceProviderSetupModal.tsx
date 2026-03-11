"use client";

import Image from "next/image";
import { FunctionComponent, useState, useEffect } from "react";
import {
  AzureIcon,
  ElevenLabsIcon,
  OpenAIIcon,
} from "@/components/icons/icons";
import Modal from "@/refresh-components/Modal";
import Button from "@/refresh-components/buttons/Button";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import InputComboBox from "@/refresh-components/inputs/InputComboBox";
import { Vertical, Horizontal } from "@/layouts/input-layouts";
import { toast } from "@/hooks/useToast";
import { Section } from "@/layouts/general-layouts";
import { SvgArrowExchange, SvgOnyxLogo } from "@opal/icons";
import type { IconProps } from "@opal/types";
import { VoiceProviderView } from "@/hooks/useVoiceProviders";
import {
  testVoiceProvider,
  upsertVoiceProvider,
  fetchVoicesByType,
  fetchLLMProviders,
} from "@/lib/admin/voice/svc";

interface VoiceOption {
  value: string;
  label: string;
  description?: string;
}

interface LLMProviderView {
  id: number;
  name: string;
  provider: string;
  api_key: string | null;
}

interface ApiKeyOption {
  value: string;
  label: string;
  description?: string;
}

interface VoiceProviderSetupModalProps {
  providerType: string;
  existingProvider: VoiceProviderView | null;
  mode: "stt" | "tts";
  defaultModelId?: string | null;
  onClose: () => void;
  onSuccess: () => void;
}

const PROVIDER_LABELS: Record<string, string> = {
  openai: "OpenAI",
  azure: "Azure Speech Services",
  elevenlabs: "ElevenLabs",
};

const PROVIDER_API_KEY_URLS: Record<string, string> = {
  openai: "https://platform.openai.com/api-keys",
  azure: "https://portal.azure.com/",
  elevenlabs: "https://elevenlabs.io/app/settings/api-keys",
};

const PROVIDER_LOGO_URLS: Record<string, string> = {
  openai: "/Openai.svg",
  azure: "/Azure.png",
  elevenlabs: "/ElevenLabs.svg",
};

const PROVIDER_DOCS_URLS: Record<string, string> = {
  openai: "https://platform.openai.com/docs/guides/text-to-speech",
  azure: "https://learn.microsoft.com/en-us/azure/ai-services/speech-service/",
  elevenlabs: "https://elevenlabs.io/docs",
};

const PROVIDER_VOICE_DOCS_URLS: Record<string, { url: string; label: string }> =
  {
    openai: {
      url: "https://platform.openai.com/docs/guides/text-to-speech#voice-options",
      label: "OpenAI",
    },
    azure: {
      url: "https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support?tabs=tts",
      label: "Azure",
    },
    elevenlabs: {
      url: "https://elevenlabs.io/docs/voices/premade-voices",
      label: "ElevenLabs",
    },
  };

const OPENAI_STT_MODELS = [{ id: "whisper-1", name: "Whisper v1" }];

const OPENAI_TTS_MODELS = [
  { id: "tts-1", name: "TTS-1" },
  { id: "tts-1-hd", name: "TTS-1 HD" },
];

// Map model IDs from cards to actual API model IDs
const MODEL_ID_MAP: Record<string, string> = {
  "tts-1": "tts-1",
  "tts-1-hd": "tts-1-hd",
  whisper: "whisper-1",
};

export default function VoiceProviderSetupModal({
  providerType,
  existingProvider,
  mode,
  defaultModelId,
  onClose,
  onSuccess,
}: VoiceProviderSetupModalProps) {
  // Map the card model ID to the actual API model ID
  // Prioritize defaultModelId (from the clicked card) over stored value
  const initialTtsModel = defaultModelId
    ? MODEL_ID_MAP[defaultModelId] ?? "tts-1"
    : existingProvider?.tts_model ?? "tts-1";

  const [apiKey, setApiKey] = useState("");
  const [apiKeyChanged, setApiKeyChanged] = useState(false);
  const [targetUri, setTargetUri] = useState(
    existingProvider?.target_uri ?? ""
  );
  const [selectedLlmProviderId, setSelectedLlmProviderId] = useState<
    number | null
  >(null);
  const [sttModel, setSttModel] = useState(
    existingProvider?.stt_model ?? "whisper-1"
  );
  const [ttsModel, setTtsModel] = useState(initialTtsModel);
  const [defaultVoice, setDefaultVoice] = useState(
    existingProvider?.default_voice ?? ""
  );
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Dynamic voices fetched from backend
  const [voiceOptions, setVoiceOptions] = useState<VoiceOption[]>([]);
  const [isLoadingVoices, setIsLoadingVoices] = useState(false);

  // Existing OpenAI LLM providers for API key reuse
  const [existingApiKeyOptions, setExistingApiKeyOptions] = useState<
    ApiKeyOption[]
  >([]);
  const [llmProviderMap, setLlmProviderMap] = useState<Map<string, number>>(
    new Map()
  );

  // Fetch existing OpenAI LLM providers (for API key reuse)
  useEffect(() => {
    if (providerType !== "openai") return;

    fetchLLMProviders()
      .then((res) => res.json())
      .then((data: LLMProviderView[]) => {
        const openaiProviders = data.filter(
          (p) => p.provider === "openai" && p.api_key
        );
        const options: ApiKeyOption[] = openaiProviders.map((p) => ({
          value: p.api_key!,
          label: p.api_key!,
          description: `Used for LLM provider ${p.name}`,
        }));
        setExistingApiKeyOptions(options);

        // Map masked API keys to provider IDs for lookup on selection
        const providerMap = new Map<string, number>();
        openaiProviders.forEach((p) => {
          if (p.api_key) {
            providerMap.set(p.api_key, p.id);
          }
        });
        setLlmProviderMap(providerMap);
      })
      .catch(() => {
        setExistingApiKeyOptions([]);
      });
  }, [providerType]);

  // Fetch voices on mount (works without API key for ElevenLabs/OpenAI)
  useEffect(() => {
    setIsLoadingVoices(true);
    fetchVoicesByType(providerType)
      .then((res) => res.json())
      .then((data: Array<{ id: string; name: string }>) => {
        const options = data.map((v) => ({
          value: v.id,
          label: v.name,
          description: v.id,
        }));
        setVoiceOptions(options);
        // Set default voice to first option if not already set,
        // or if current value doesn't exist in the new options
        setDefaultVoice((prev) => {
          if (!prev) return options[0]?.value ?? "";
          const existsInOptions = options.some((opt) => opt.value === prev);
          return existsInOptions ? prev : options[0]?.value ?? "";
        });
      })
      .catch(() => {
        setVoiceOptions([]);
      })
      .finally(() => {
        setIsLoadingVoices(false);
      });
  }, [providerType]);

  const isEditing = !!existingProvider;
  const label = PROVIDER_LABELS[providerType] ?? providerType;

  // Logo arrangement component for the modal header
  // No useMemo needed - providerType and label are stable props
  const LogoArrangement: FunctionComponent<IconProps> = () => (
    <div className="flex items-center gap-2">
      <div className="flex items-center justify-center size-7 shrink-0 overflow-clip">
        {providerType === "openai" ? (
          <OpenAIIcon size={24} />
        ) : providerType === "azure" ? (
          <AzureIcon size={24} />
        ) : providerType === "elevenlabs" ? (
          <ElevenLabsIcon size={24} />
        ) : (
          <Image
            src={PROVIDER_LOGO_URLS[providerType] ?? "/Openai.svg"}
            alt={`${label} logo`}
            width={24}
            height={24}
            className="object-contain"
          />
        )}
      </div>
      <div className="flex items-center justify-center size-4 shrink-0">
        <SvgArrowExchange className="size-3 text-text-04" />
      </div>
      <div className="flex items-center justify-center size-7 p-0.5 shrink-0 overflow-clip">
        <SvgOnyxLogo size={24} className="text-text-04 shrink-0" />
      </div>
    </div>
  );

  const handleSubmit = async () => {
    // API key required for new providers, or when explicitly changed during edit
    if (!selectedLlmProviderId) {
      if (!isEditing && !apiKey) {
        toast.error("API key is required");
        return;
      }
      if (isEditing && apiKeyChanged && !apiKey) {
        toast.error(
          "API key cannot be empty. Leave blank to keep existing key."
        );
        return;
      }
    }

    if (providerType === "azure" && !isEditing && !targetUri) {
      toast.error("Target URI is required");
      return;
    }

    setIsSubmitting(true);
    try {
      // Test the connection first (skip if reusing LLM provider key - it's already validated)
      if (!selectedLlmProviderId) {
        const testResponse = await testVoiceProvider({
          provider_type: providerType,
          api_key: apiKeyChanged ? apiKey : undefined,
          target_uri: targetUri || undefined,
          use_stored_key: isEditing && !apiKeyChanged,
        });

        if (!testResponse.ok) {
          const data = await testResponse.json();
          toast.error(data.detail || "Connection test failed");
          setIsSubmitting(false);
          return;
        }
      }

      // Save the provider
      const response = await upsertVoiceProvider({
        id: existingProvider?.id,
        name: label,
        provider_type: providerType,
        api_key: selectedLlmProviderId
          ? undefined
          : apiKeyChanged
            ? apiKey
            : undefined,
        api_key_changed: selectedLlmProviderId ? false : apiKeyChanged,
        target_uri: targetUri || undefined,
        llm_provider_id: selectedLlmProviderId,
        stt_model: sttModel,
        tts_model: ttsModel,
        default_voice: defaultVoice,
        activate_stt: mode === "stt",
        activate_tts: mode === "tts",
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
          icon={LogoArrangement}
          title={isEditing ? `Edit ${label}` : `Set up ${label}`}
          description={`Connect to ${label} and set up your voice models.`}
          onClose={onClose}
        />
        <Modal.Body>
          <Section gap={1} alignItems="stretch">
            <Vertical
              title="API Key"
              subDescription={
                isEditing ? (
                  "Leave blank to keep existing key"
                ) : (
                  <>
                    Paste your{" "}
                    <a
                      href={PROVIDER_API_KEY_URLS[providerType]}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="underline"
                    >
                      API key
                    </a>{" "}
                    from {label} to access your models.
                  </>
                )
              }
              nonInteractive
            >
              {providerType === "openai" && existingApiKeyOptions.length > 0 ? (
                <InputComboBox
                  placeholder={isEditing ? "••••••••" : "Enter API key"}
                  value={apiKey}
                  onChange={(e) => {
                    setApiKey(e.target.value);
                    setApiKeyChanged(true);
                    setSelectedLlmProviderId(null);
                  }}
                  onValueChange={(value) => {
                    setApiKey(value);
                    // Check if this is an existing key
                    const llmProviderId = llmProviderMap.get(value);
                    if (llmProviderId) {
                      setSelectedLlmProviderId(llmProviderId);
                      setApiKeyChanged(false);
                    } else {
                      setSelectedLlmProviderId(null);
                      setApiKeyChanged(true);
                    }
                  }}
                  options={existingApiKeyOptions}
                  separatorLabel="Reuse OpenAI API Keys"
                  strict={false}
                  showAddPrefix
                />
              ) : (
                <InputTypeIn
                  type="password"
                  placeholder={isEditing ? "••••••••" : "Enter API key"}
                  value={apiKey}
                  onChange={(e) => {
                    setApiKey(e.target.value);
                    setApiKeyChanged(true);
                  }}
                />
              )}
            </Vertical>

            {providerType === "azure" && (
              <Vertical
                title="Target URI"
                subDescription={
                  <>
                    Paste the endpoint shown in{" "}
                    <a
                      href="https://portal.azure.com/"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="underline"
                    >
                      Azure Portal (Keys and Endpoint)
                    </a>
                    . Onyx extracts the speech region from this URL. Examples:
                    https://westus.api.cognitive.microsoft.com/ or
                    https://westus.tts.speech.microsoft.com/.
                  </>
                }
                nonInteractive
              >
                <InputTypeIn
                  placeholder={
                    isEditing
                      ? "Leave blank to keep existing"
                      : "https://<region>.api.cognitive.microsoft.com/"
                  }
                  value={targetUri}
                  onChange={(e) => setTargetUri(e.target.value)}
                />
              </Vertical>
            )}

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
              <Vertical
                title="Default Model"
                subDescription="This model will be used by Onyx by default for text-to-speech."
                nonInteractive
              >
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
              </Vertical>
            )}

            {mode === "tts" && (
              <Vertical
                title="Voice"
                subDescription={
                  <>
                    This voice will be used for spoken responses. See full list
                    of supported languages and voices at{" "}
                    <a
                      href={
                        PROVIDER_VOICE_DOCS_URLS[providerType]?.url ??
                        PROVIDER_DOCS_URLS[providerType]
                      }
                      target="_blank"
                      rel="noopener noreferrer"
                      className="underline"
                    >
                      {PROVIDER_VOICE_DOCS_URLS[providerType]?.label ?? label}
                    </a>
                    .
                  </>
                }
                nonInteractive
              >
                <InputComboBox
                  value={defaultVoice}
                  onValueChange={setDefaultVoice}
                  options={voiceOptions}
                  placeholder={
                    isLoadingVoices
                      ? "Loading voices..."
                      : "Select a voice or enter voice ID"
                  }
                  disabled={isLoadingVoices}
                  strict={false}
                />
              </Vertical>
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
