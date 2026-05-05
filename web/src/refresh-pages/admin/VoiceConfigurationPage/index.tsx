"use client";

import { useMemo } from "react";
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
} from "@/lib/voice/svc";
import { ThreeDotsLoader } from "@/components/Loading";
import { toast } from "@/hooks/useToast";
import { Content } from "@opal/layouts";
import { MessageCard, Text } from "@opal/components";
import { Section } from "@/layouts/general-layouts";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import {
  getProviderIcon,
  getProviderLabel,
  VoiceProviderSetupModal,
  VoiceDisconnectModal,
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

interface ModelCardProps {
  model: ModelDetails;
  mode: ProviderMode;
  provider: VoiceProviderView | undefined;
  status: "disconnected" | "connected" | "selected";
  onSelect: () => void;
  onDeselect: () => void;
  onMutate: () => void;
}

function ModelCard({
  model,
  mode,
  provider,
  status,
  onSelect,
  onDeselect,
  onMutate,
}: ModelCardProps) {
  const setupModal = useCreateModal();
  const disconnectModal = useCreateModal();

  const handleDisconnect = async () => {
    if (!provider) return;
    try {
      const response = await deleteVoiceProvider(provider.id);
      if (!response.ok) {
        const errorBody = await response.json().catch(() => ({}));
        throw new Error(
          typeof errorBody?.detail === "string"
            ? errorBody.detail
            : "Failed to disconnect provider."
        );
      }
      toast.success(`${getProviderLabel(model.providerType)} disconnected`);
      onMutate();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Unexpected error occurred."
      );
    } finally {
      disconnectModal.toggle(false);
    }
  };

  const handleSetupSuccess = () => {
    onMutate();
    setupModal.toggle(false);
  };

  return (
    <>
      <setupModal.Provider>
        <VoiceProviderSetupModal
          providerType={model.providerType}
          existingProvider={status !== "disconnected" ? provider ?? null : null}
          mode={mode}
          defaultModelId={model.id}
          onSuccess={handleSetupSuccess}
        />
      </setupModal.Provider>

      <disconnectModal.Provider>
        <VoiceDisconnectModal
          disconnectTarget={{
            providerId: provider?.id ?? 0,
            providerLabel: getProviderLabel(model.providerType),
            providerType: model.providerType,
          }}
          providers={[]}
          onDisconnect={() => void handleDisconnect()}
        />
      </disconnectModal.Provider>

      <ProviderCard
        aria-label={`voice-${mode}-${model.id}`}
        icon={getProviderIcon(model.providerType)}
        title={model.label}
        description={model.subtitle}
        status={status}
        onConnect={() => setupModal.toggle(true)}
        onSelect={onSelect}
        onDeselect={onDeselect}
        onEdit={() => setupModal.toggle(true)}
        onDisconnect={
          status !== "disconnected" && provider
            ? () => disconnectModal.toggle(true)
            : undefined
        }
        disconnectModalOpen={disconnectModal.isOpen}
      />
    </>
  );
}

export default function VoiceConfigurationPage() {
  const { providers, isLoading, refresh: mutate } = useVoiceProviders();

  const providersByType = useMemo(() => {
    return new Map((providers ?? []).map((p) => [p.provider_type, p] as const));
  }, [providers]);

  const hasActiveSTTProvider =
    providers?.some((p) => p.is_default_stt) ?? false;
  const hasActiveTTSProvider =
    providers?.some((p) => p.is_default_tts) ?? false;

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

  const getModelStatus = (
    model: ModelDetails,
    mode: ProviderMode
  ): "disconnected" | "connected" | "selected" => {
    const provider = providersByType.get(model.providerType);
    if (!provider || !provider.has_api_key) return "disconnected";

    const isActive =
      mode === "stt"
        ? provider.is_default_stt
        : provider.is_default_tts && provider.tts_model === model.id;

    if (isActive) return "selected";
    return "connected";
  };

  return (
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
              {STT_MODELS.map((model) => (
                <ModelCard
                  key={`stt-${model.id}`}
                  model={model}
                  mode="stt"
                  provider={providersByType.get(model.providerType)}
                  status={getModelStatus(model, "stt")}
                  onSelect={() => {
                    const p = providersByType.get(model.providerType);
                    if (p?.id)
                      activateVoiceProvider(p.id, "stt", model.id).then(() =>
                        mutate()
                      );
                  }}
                  onDeselect={() => {
                    const p = providersByType.get(model.providerType);
                    if (p?.id)
                      deactivateVoiceProvider(p.id, "stt").then(() => mutate());
                  }}
                  onMutate={() => mutate()}
                />
              ))}
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
                  {group.models.map((model) => (
                    <ModelCard
                      key={`tts-${model.id}`}
                      model={model}
                      mode="tts"
                      provider={providersByType.get(model.providerType)}
                      status={getModelStatus(model, "tts")}
                      onSelect={() => {
                        const p = providersByType.get(model.providerType);
                        if (p?.id)
                          activateVoiceProvider(p.id, "tts", model.id).then(
                            () => mutate()
                          );
                      }}
                      onDeselect={() => {
                        const p = providersByType.get(model.providerType);
                        if (p?.id)
                          deactivateVoiceProvider(p.id, "tts").then(() =>
                            mutate()
                          );
                      }}
                      onMutate={() => mutate()}
                    />
                  ))}
                </div>
              ))}
            </Section>
          </Section>
        </Section>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
