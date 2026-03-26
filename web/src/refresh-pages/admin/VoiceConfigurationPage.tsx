"use client";

import { useMemo, useState } from "react";
import {
  AzureIcon,
  ElevenLabsIcon,
  IconProps,
  OpenAIIcon,
} from "@/components/icons/icons";
// TODO(@raunakab): migrate this `refresh-components/Text` to `@opal/components` Text
import Text from "@/refresh-components/texts/Text";
import { Select } from "@/refresh-components/cards";
import Message from "@/refresh-components/messages/Message";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { FetchError } from "@/lib/fetcher";
import {
  useVoiceProviders,
  VoiceProviderView,
} from "@/hooks/useVoiceProviders";
import {
  activateVoiceProvider,
  deactivateVoiceProvider,
} from "@/lib/admin/voice/svc";
import { ThreeDotsLoader } from "@/components/Loading";
import { Callout } from "@/components/ui/callout";
import { Content } from "@opal/layouts";
import { SvgMicrophone } from "@opal/icons";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import VoiceProviderSetupModal from "@/app/admin/configuration/voice/VoiceProviderSetupModal";

interface ModelDetails {
  id: string;
  label: string;
  subtitle: string;
  providerType: string;
}

interface ProviderGroup {
  providerType: string;
  providerLabel: string;
  models: ModelDetails[];
}

// STT Models - individual cards
const STT_MODELS: ModelDetails[] = [
  {
    id: "whisper",
    label: "Whisper",
    subtitle: "OpenAI's general purpose speech recognition model.",
    providerType: "openai",
  },
  {
    id: "azure-speech-stt",
    label: "Azure Speech",
    subtitle: "Speech to text in Microsoft Foundry Tools.",
    providerType: "azure",
  },
  {
    id: "elevenlabs-stt",
    label: "ElevenAPI",
    subtitle: "ElevenLabs Speech to Text API.",
    providerType: "elevenlabs",
  },
];

// TTS Models - grouped by provider
const TTS_PROVIDER_GROUPS: ProviderGroup[] = [
  {
    providerType: "openai",
    providerLabel: "OpenAI",
    models: [
      {
        id: "tts-1",
        label: "TTS-1",
        subtitle: "OpenAI's text-to-speech model optimized for speed.",
        providerType: "openai",
      },
      {
        id: "tts-1-hd",
        label: "TTS-1 HD",
        subtitle: "OpenAI's text-to-speech model optimized for quality.",
        providerType: "openai",
      },
    ],
  },
  {
    providerType: "azure",
    providerLabel: "Azure",
    models: [
      {
        id: "azure-speech-tts",
        label: "Azure Speech",
        subtitle: "Text to speech in Microsoft Foundry Tools.",
        providerType: "azure",
      },
    ],
  },
  {
    providerType: "elevenlabs",
    providerLabel: "ElevenLabs",
    models: [
      {
        id: "elevenlabs-tts",
        label: "ElevenAPI",
        subtitle: "ElevenLabs Text to Speech API.",
        providerType: "elevenlabs",
      },
    ],
  },
];

const FallbackMicrophoneIcon = ({ size, className }: IconProps) => (
  <SvgMicrophone size={size} className={className} />
);

function getProviderIcon(
  providerType: string
): React.FunctionComponent<IconProps> {
  switch (providerType) {
    case "openai":
      return OpenAIIcon;
    case "azure":
      return AzureIcon;
    case "elevenlabs":
      return ElevenLabsIcon;
    default:
      return FallbackMicrophoneIcon;
  }
}

type ProviderMode = "stt" | "tts";

const route = ADMIN_ROUTES.VOICE;
const pageDescription =
  "Configure speech-to-text and text-to-speech providers for voice input and spoken responses.";

export default function VoiceConfigurationPage() {
  const [modalOpen, setModalOpen] = useState(false);
  const [selectedProvider, setSelectedProvider] = useState<string | null>(null);
  const [editingProvider, setEditingProvider] =
    useState<VoiceProviderView | null>(null);
  const [modalMode, setModalMode] = useState<ProviderMode>("stt");
  const [selectedModelId, setSelectedModelId] = useState<string | null>(null);
  const [sttActivationError, setSTTActivationError] = useState<string | null>(
    null
  );
  const [ttsActivationError, setTTSActivationError] = useState<string | null>(
    null
  );

  const { providers, error, isLoading, refresh: mutate } = useVoiceProviders();

  const handleConnect = (
    providerType: string,
    mode: ProviderMode,
    modelId?: string
  ) => {
    setSelectedProvider(providerType);
    setEditingProvider(null);
    setModalMode(mode);
    setSelectedModelId(modelId ?? null);
    setModalOpen(true);
    setSTTActivationError(null);
    setTTSActivationError(null);
  };

  const handleEdit = (
    provider: VoiceProviderView,
    mode: ProviderMode,
    modelId?: string
  ) => {
    setSelectedProvider(provider.provider_type);
    setEditingProvider(provider);
    setModalMode(mode);
    setSelectedModelId(modelId ?? null);
    setModalOpen(true);
    setSTTActivationError(null);
    setTTSActivationError(null);
  };

  const handleSetDefault = async (
    providerId: number,
    mode: ProviderMode,
    modelId?: string
  ) => {
    const setError =
      mode === "stt" ? setSTTActivationError : setTTSActivationError;
    setError(null);
    try {
      const response = await activateVoiceProvider(providerId, mode, modelId);
      if (!response.ok) {
        const errorBody = await response.json().catch(() => ({}));
        throw new Error(
          typeof errorBody?.detail === "string"
            ? errorBody.detail
            : `Failed to set provider as default ${mode.toUpperCase()}.`
        );
      }
      await mutate();
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Unexpected error occurred.";
      setError(message);
    }
  };

  const handleDeactivate = async (providerId: number, mode: ProviderMode) => {
    const setError =
      mode === "stt" ? setSTTActivationError : setTTSActivationError;
    setError(null);
    try {
      const response = await deactivateVoiceProvider(providerId, mode);
      if (!response.ok) {
        const errorBody = await response.json().catch(() => ({}));
        throw new Error(
          typeof errorBody?.detail === "string"
            ? errorBody.detail
            : `Failed to deactivate ${mode.toUpperCase()} provider.`
        );
      }
      await mutate();
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Unexpected error occurred.";
      setError(message);
    }
  };

  const handleModalClose = () => {
    setModalOpen(false);
    setSelectedProvider(null);
    setEditingProvider(null);
    setSelectedModelId(null);
  };

  const handleModalSuccess = () => {
    mutate();
    handleModalClose();
  };

  const isProviderConfigured = (provider?: VoiceProviderView): boolean => {
    return !!provider?.has_api_key;
  };

  const providersByType = useMemo(() => {
    return new Map((providers ?? []).map((p) => [p.provider_type, p] as const));
  }, [providers]);

  const hasActiveSTTProvider =
    providers?.some((p) => p.is_default_stt) ?? false;
  const hasActiveTTSProvider =
    providers?.some((p) => p.is_default_tts) ?? false;

  const getModelStatus = (
    model: ModelDetails,
    mode: ProviderMode
  ): "disconnected" | "connected" | "selected" => {
    const provider = providersByType.get(model.providerType);
    if (!provider || !isProviderConfigured(provider)) return "disconnected";

    const isActive =
      mode === "stt"
        ? provider.is_default_stt
        : provider.is_default_tts && provider.tts_model === model.id;

    if (isActive) return "selected";
    return "connected";
  };

  const renderModelSelect = (model: ModelDetails, mode: ProviderMode) => {
    const provider = providersByType.get(model.providerType);
    const status = getModelStatus(model, mode);
    const Icon = getProviderIcon(model.providerType);

    return (
      <Select
        key={`${mode}-${model.id}`}
        aria-label={`voice-${mode}-${model.id}`}
        icon={Icon}
        title={model.label}
        description={model.subtitle}
        status={status}
        onConnect={() => handleConnect(model.providerType, mode, model.id)}
        onSelect={() => {
          if (provider?.id) handleSetDefault(provider.id, mode, model.id);
        }}
        onDeselect={() => {
          if (provider?.id) handleDeactivate(provider.id, mode);
        }}
        onEdit={() => {
          if (provider) handleEdit(provider, mode, model.id);
        }}
      />
    );
  };

  if (error) {
    const message = error?.message || "Unable to load voice configuration.";
    const detail =
      error instanceof FetchError && typeof error.info?.detail === "string"
        ? error.info.detail
        : undefined;

    return (
      <SettingsLayouts.Root>
        <SettingsLayouts.Header
          icon={route.icon}
          title={route.title}
          description={pageDescription}
        />
        <SettingsLayouts.Body>
          <Callout type="danger" title="Failed to load voice settings">
            {message}
            {detail && (
              <Text as="p" mainContentBody text03>
                {detail}
              </Text>
            )}
          </Callout>
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }

  if (isLoading) {
    return (
      <SettingsLayouts.Root>
        <SettingsLayouts.Header
          icon={route.icon}
          title={route.title}
          description={pageDescription}
        />
        <SettingsLayouts.Body>
          <ThreeDotsLoader />
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title={route.title}
        description={pageDescription}
      />
      <SettingsLayouts.Body>
        <div className="flex flex-col gap-6">
          <Content
            title="Speech to Text"
            description="Select a model to transcribe speech to text in chats."
            sizePreset="main-content"
            variant="section"
          />

          {sttActivationError && (
            <Callout type="danger" title="Unable to update STT provider">
              {sttActivationError}
            </Callout>
          )}

          {!hasActiveSTTProvider && (
            <Message
              info
              static
              large
              close={false}
              text="Connect a speech to text provider to use in chat."
              className="w-full"
            />
          )}

          <div className="flex flex-col gap-2">
            {STT_MODELS.map((model) => renderModelSelect(model, "stt"))}
          </div>
        </div>

        <div className="flex flex-col gap-6">
          <Content
            title="Text to Speech"
            description="Select a model to speak out chat responses."
            sizePreset="main-content"
            variant="section"
          />

          {ttsActivationError && (
            <Callout type="danger" title="Unable to update TTS provider">
              {ttsActivationError}
            </Callout>
          )}

          {!hasActiveTTSProvider && (
            <Message
              info
              static
              large
              close={false}
              text="Connect a text to speech provider to use in chat."
              className="w-full"
            />
          )}

          {TTS_PROVIDER_GROUPS.map((group) => (
            <div key={group.providerType} className="flex flex-col gap-2">
              <Text secondaryBody text03>
                {group.providerLabel}
              </Text>
              <div className="flex flex-col gap-2">
                {group.models.map((model) => renderModelSelect(model, "tts"))}
              </div>
            </div>
          ))}
        </div>
      </SettingsLayouts.Body>

      {modalOpen && selectedProvider && (
        <VoiceProviderSetupModal
          providerType={selectedProvider}
          existingProvider={editingProvider}
          mode={modalMode}
          defaultModelId={selectedModelId}
          onClose={handleModalClose}
          onSuccess={handleModalSuccess}
        />
      )}
    </SettingsLayouts.Root>
  );
}
