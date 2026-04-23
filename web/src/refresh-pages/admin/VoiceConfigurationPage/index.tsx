"use client";

import { useMemo, useState } from "react";
import ProviderCard from "@/sections/admin/ProviderCard";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import {
  useVoiceProviders,
  VoiceProviderView,
} from "@/hooks/useVoiceProviders";
import {
  activateVoiceProvider,
  deactivateVoiceProvider,
  deleteVoiceProvider,
} from "@/lib/admin/voice/svc";
import { ThreeDotsLoader } from "@/components/Loading";
import { toast } from "@/hooks/useToast";
import { Content } from "@opal/layouts";
import { MessageCard, Text } from "@opal/components";
import { Section } from "@/layouts/general-layouts";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import {
  getProviderIcon,
  getProviderLabel,
  VoiceProviderSetupModal,
  VoiceDisconnectModal,
  NO_DEFAULT_VALUE,
  type ProviderMode,
} from "@/refresh-pages/admin/VoiceConfigurationPage/shared";

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
  const [disconnectTarget, setDisconnectTarget] = useState<{
    providerId: number;
    providerLabel: string;
    providerType: string;
  } | null>(null);
  const [replacementProviderId, setReplacementProviderId] = useState<
    string | null
  >(null);

  const { providers, isLoading, refresh: mutate } = useVoiceProviders();

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
  };

  const handleSetDefault = async (
    providerId: number,
    mode: ProviderMode,
    modelId?: string
  ) => {
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
      toast.error(
        err instanceof Error ? err.message : "Unexpected error occurred."
      );
    }
  };

  const handleDeactivate = async (providerId: number, mode: ProviderMode) => {
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
      toast.error(
        err instanceof Error ? err.message : "Unexpected error occurred."
      );
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

  const handleDisconnect = async () => {
    if (!disconnectTarget) return;
    try {
      const targetProvider = providers.find(
        (p) => p.id === disconnectTarget.providerId
      );

      // If a replacement was selected (not "No Default"), activate it for each
      // mode the disconnected provider was default for
      if (replacementProviderId && replacementProviderId !== NO_DEFAULT_VALUE) {
        const repId = Number(replacementProviderId);

        if (targetProvider?.is_default_stt) {
          const resp = await activateVoiceProvider(repId, "stt");
          if (!resp.ok) {
            const errorBody = await resp.json().catch(() => ({}));
            throw new Error(
              typeof errorBody?.detail === "string"
                ? errorBody.detail
                : "Failed to activate replacement STT provider."
            );
          }
        }

        if (targetProvider?.is_default_tts) {
          const resp = await activateVoiceProvider(repId, "tts");
          if (!resp.ok) {
            const errorBody = await resp.json().catch(() => ({}));
            throw new Error(
              typeof errorBody?.detail === "string"
                ? errorBody.detail
                : "Failed to activate replacement TTS provider."
            );
          }
        }
      }

      const response = await deleteVoiceProvider(disconnectTarget.providerId);
      if (!response.ok) {
        const errorBody = await response.json().catch(() => ({}));
        throw new Error(
          typeof errorBody?.detail === "string"
            ? errorBody.detail
            : "Failed to disconnect provider."
        );
      }
      await mutate();
      toast.success(`${disconnectTarget.providerLabel} disconnected`);
    } catch (err) {
      console.error("Failed to disconnect voice provider:", err);
      toast.error(
        err instanceof Error ? err.message : "Unexpected error occurred."
      );
    } finally {
      setDisconnectTarget(null);
      setReplacementProviderId(null);
    }
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
      <ProviderCard
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
        onDisconnect={
          status !== "disconnected" && provider
            ? () =>
                setDisconnectTarget({
                  providerId: provider.id,
                  providerLabel: getProviderLabel(model.providerType),
                  providerType: model.providerType,
                })
            : undefined
        }
        disconnectModalOpen={disconnectTarget?.providerId === provider?.id}
      />
    );
  };

  if (isLoading) {
    return (
      <SettingsLayouts.Root>
        <SettingsLayouts.Header
          icon={route.icon}
          title={route.title}
          description={pageDescription}
          divider
        />
        <SettingsLayouts.Body>
          <ThreeDotsLoader />
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }

  return (
    <>
      {disconnectTarget && (
        <VoiceDisconnectModal
          disconnectTarget={disconnectTarget}
          providers={providers}
          replacementProviderId={replacementProviderId}
          onReplacementChange={setReplacementProviderId}
          onClose={() => {
            setDisconnectTarget(null);
            setReplacementProviderId(null);
          }}
          onDisconnect={() => void handleDisconnect()}
        />
      )}

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

      <SettingsLayouts.Root>
        <SettingsLayouts.Header
          icon={route.icon}
          title={route.title}
          description={pageDescription}
          divider
        />
        <SettingsLayouts.Body>
          <Section gap={2}>
            <Section gap={0.75}>
              <Content
                title="Speech to Text"
                description="Select a model to transcribe speech to text in chats."
                sizePreset="main-content"
                variant="section"
              />

              {!hasActiveSTTProvider && (
                <MessageCard
                  variant="info"
                  title="Connect a speech to text provider to use in chat."
                />
              )}

              <Section gap={0.5}>
                {STT_MODELS.map((model) => renderModelSelect(model, "stt"))}
              </Section>
            </Section>

            <Section gap={0.75}>
              <Content
                title="Text to Speech"
                description="Select a model to speak out chat responses."
                sizePreset="main-content"
                variant="section"
              />

              {!hasActiveTTSProvider && (
                <MessageCard
                  variant="info"
                  title="Connect a text to speech provider to use in chat."
                />
              )}

              <Section gap={1}>
                {TTS_PROVIDER_GROUPS.map((group) => (
                  <div
                    key={group.providerType}
                    className="flex w-full flex-col gap-2"
                  >
                    <Text font="secondary-body" color="text-03">
                      {group.providerLabel}
                    </Text>
                    {group.models.map((model) =>
                      renderModelSelect(model, "tts")
                    )}
                  </div>
                ))}
              </Section>
            </Section>
          </Section>
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    </>
  );
}
