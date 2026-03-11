"use client";

import Image from "next/image";
import { useMemo, useState } from "react";
import { AdminPageTitle } from "@/components/admin/Title";
import {
  AzureIcon,
  ElevenLabsIcon,
  InfoIcon,
  OpenAIIcon,
} from "@/components/icons/icons";
import Text from "@/refresh-components/texts/Text";
import Separator from "@/refresh-components/Separator";
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
import Button from "@/refresh-components/buttons/Button";
import { Button as OpalButton } from "@opal/components";
import { cn } from "@/lib/utils";
import {
  SvgArrowExchange,
  SvgArrowRightCircle,
  SvgAudio,
  SvgCheckSquare,
  SvgEdit,
  SvgMicrophone,
  SvgX,
} from "@opal/icons";
import VoiceProviderSetupModal from "./VoiceProviderSetupModal";

interface ModelDetails {
  id: string;
  label: string;
  subtitle: string;
  logoSrc?: string;
  providerType: string;
}

interface ProviderGroup {
  providerType: string;
  providerLabel: string;
  logoSrc?: string;
  models: ModelDetails[];
}

// STT Models - individual cards
const STT_MODELS: ModelDetails[] = [
  {
    id: "whisper",
    label: "Whisper",
    subtitle: "OpenAI's general purpose speech recognition model.",
    logoSrc: "/Openai.svg",
    providerType: "openai",
  },
  {
    id: "azure-speech-stt",
    label: "Azure Speech",
    subtitle: "Speech to text in Microsoft Foundry Tools.",
    logoSrc: "/Azure.png",
    providerType: "azure",
  },
  {
    id: "elevenlabs-stt",
    label: "ElevenAPI",
    subtitle: "ElevenLabs Speech to Text API.",
    logoSrc: "/ElevenLabs.svg",
    providerType: "elevenlabs",
  },
];

// TTS Models - grouped by provider
const TTS_PROVIDER_GROUPS: ProviderGroup[] = [
  {
    providerType: "openai",
    providerLabel: "OpenAI",
    logoSrc: "/Openai.svg",
    models: [
      {
        id: "tts-1",
        label: "TTS-1",
        subtitle: "OpenAI's text-to-speech model optimized for speed.",
        logoSrc: "/Openai.svg",
        providerType: "openai",
      },
      {
        id: "tts-1-hd",
        label: "TTS-1 HD",
        subtitle: "OpenAI's text-to-speech model optimized for quality.",
        logoSrc: "/Openai.svg",
        providerType: "openai",
      },
    ],
  },
  {
    providerType: "azure",
    providerLabel: "Azure",
    logoSrc: "/Azure.png",
    models: [
      {
        id: "azure-speech-tts",
        label: "Azure Speech",
        subtitle: "Text to speech in Microsoft Foundry Tools.",
        logoSrc: "/Azure.png",
        providerType: "azure",
      },
    ],
  },
  {
    providerType: "elevenlabs",
    providerLabel: "ElevenLabs",
    logoSrc: "/ElevenLabs.svg",
    models: [
      {
        id: "elevenlabs-tts",
        label: "ElevenAPI",
        subtitle: "ElevenLabs Text to Speech API.",
        logoSrc: "/ElevenLabs.svg",
        providerType: "elevenlabs",
      },
    ],
  },
];

interface HoverIconButtonProps extends React.ComponentProps<typeof Button> {
  isHovered: boolean;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
  children: React.ReactNode;
}

function HoverIconButton({
  isHovered,
  onMouseEnter,
  onMouseLeave,
  children,
  ...buttonProps
}: HoverIconButtonProps) {
  return (
    <div onMouseEnter={onMouseEnter} onMouseLeave={onMouseLeave}>
      <Button {...buttonProps} rightIcon={isHovered ? SvgX : SvgCheckSquare}>
        {children}
      </Button>
    </div>
  );
}

type ProviderMode = "stt" | "tts";

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
  const [hoveredButtonKey, setHoveredButtonKey] = useState<string | null>(null);

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

  // Map provider types to their configured provider data
  const providersByType = useMemo(() => {
    return new Map((providers ?? []).map((p) => [p.provider_type, p] as const));
  }, [providers]);

  const hasActiveSTTProvider =
    providers?.some((p) => p.is_default_stt) ?? false;
  const hasActiveTTSProvider =
    providers?.some((p) => p.is_default_tts) ?? false;

  const renderLogo = ({
    logoSrc,
    providerType,
    alt,
    size = 16,
  }: {
    logoSrc?: string;
    providerType: string;
    alt: string;
    size?: number;
  }) => {
    const containerSizeClass = size === 24 ? "size-7" : "size-5";

    return (
      <div
        className={cn(
          "flex items-center justify-center px-0.5 py-0 shrink-0 overflow-clip",
          containerSizeClass
        )}
      >
        {providerType === "openai" ? (
          <OpenAIIcon size={size} />
        ) : providerType === "azure" ? (
          <AzureIcon size={size} />
        ) : providerType === "elevenlabs" ? (
          <ElevenLabsIcon size={size} />
        ) : logoSrc ? (
          <Image
            src={logoSrc}
            alt={alt}
            width={size}
            height={size}
            className="object-contain"
          />
        ) : (
          <SvgMicrophone size={size} className="text-text-02" />
        )}
      </div>
    );
  };

  const renderModelCard = ({
    model,
    mode,
  }: {
    model: ModelDetails;
    mode: ProviderMode;
  }) => {
    const provider = providersByType.get(model.providerType);
    const isConfigured = isProviderConfigured(provider);
    // For TTS, also check that this specific model is the default (not just the provider)
    const isActive =
      mode === "stt"
        ? provider?.is_default_stt
        : provider?.is_default_tts && provider?.tts_model === model.id;
    const isHighlighted = isActive ?? false;
    const providerId = provider?.id;

    const buttonState = (() => {
      if (!provider || !isConfigured) {
        return {
          label: "Connect",
          disabled: false,
          icon: "arrow" as const,
          onClick: () => handleConnect(model.providerType, mode, model.id),
        };
      }

      if (isActive) {
        return {
          label: "Current Default",
          disabled: false,
          icon: "check" as const,
          onClick: providerId
            ? () => handleDeactivate(providerId, mode)
            : undefined,
        };
      }

      return {
        label: "Set as Default",
        disabled: false,
        icon: "arrow-circle" as const,
        onClick: providerId
          ? () => handleSetDefault(providerId, mode, model.id)
          : undefined,
      };
    })();

    const buttonKey = `${mode}-${model.id}`;
    const isButtonHovered = hoveredButtonKey === buttonKey;
    const isCardClickable =
      buttonState.icon === "arrow" &&
      typeof buttonState.onClick === "function" &&
      !buttonState.disabled;

    const handleCardClick = () => {
      if (isCardClickable) {
        buttonState.onClick?.();
      }
    };

    return (
      <div
        key={`${mode}-${model.id}`}
        onClick={isCardClickable ? handleCardClick : undefined}
        className={cn(
          "flex items-start justify-between gap-4 rounded-16 border p-2 bg-background-neutral-01",
          isHighlighted ? "border-action-link-05" : "border-border-01",
          isCardClickable &&
            "cursor-pointer hover:bg-background-tint-01 transition-colors"
        )}
      >
        <div className="flex flex-1 items-start gap-2.5 p-2">
          {renderLogo({
            logoSrc: model.logoSrc,
            providerType: model.providerType,
            alt: `${model.label} logo`,
            size: 16,
          })}
          <div className="flex flex-col gap-0.5">
            <Text as="p" mainUiAction text04>
              {model.label}
            </Text>
            <Text as="p" secondaryBody text03>
              {model.subtitle}
            </Text>
          </div>
        </div>
        <div className="flex items-center justify-end gap-1.5 self-center">
          {isConfigured && (
            <OpalButton
              icon={SvgEdit}
              tooltip="Edit"
              prominence="tertiary"
              size="sm"
              onClick={(e) => {
                e.stopPropagation();
                if (provider) handleEdit(provider, mode, model.id);
              }}
              aria-label={`Edit ${model.label}`}
            />
          )}
          {buttonState.icon === "check" ? (
            <HoverIconButton
              isHovered={isButtonHovered}
              onMouseEnter={() => setHoveredButtonKey(buttonKey)}
              onMouseLeave={() => setHoveredButtonKey(null)}
              action={true}
              tertiary
              disabled={buttonState.disabled}
              onClick={(e) => {
                e.stopPropagation();
                buttonState.onClick?.();
              }}
            >
              {buttonState.label}
            </HoverIconButton>
          ) : (
            <Button
              action={false}
              tertiary
              disabled={buttonState.disabled || !buttonState.onClick}
              onClick={(e) => {
                e.stopPropagation();
                buttonState.onClick?.();
              }}
              rightIcon={
                buttonState.icon === "arrow"
                  ? SvgArrowExchange
                  : buttonState.icon === "arrow-circle"
                    ? SvgArrowRightCircle
                    : undefined
              }
            >
              {buttonState.label}
            </Button>
          )}
        </div>
      </div>
    );
  };

  if (error) {
    const message = error?.message || "Unable to load voice configuration.";
    const detail =
      error instanceof FetchError && typeof error.info?.detail === "string"
        ? error.info.detail
        : undefined;

    return (
      <>
        <AdminPageTitle
          title="Voice"
          icon={SvgMicrophone}
          includeDivider={false}
        />
        <Callout type="danger" title="Failed to load voice settings">
          {message}
          {detail && (
            <Text as="p" className="mt-2 text-text-03" mainContentBody text03>
              {detail}
            </Text>
          )}
        </Callout>
      </>
    );
  }

  if (isLoading) {
    return (
      <>
        <AdminPageTitle
          title="Voice"
          icon={SvgMicrophone}
          includeDivider={false}
        />
        <div className="mt-8">
          <ThreeDotsLoader />
        </div>
      </>
    );
  }

  return (
    <>
      <AdminPageTitle icon={SvgAudio} title="Voice" />
      <div className="pt-4 pb-4">
        <Text as="p" secondaryBody text03>
          Speech to text (STT) and text to speech (TTS) capabilities.
        </Text>
      </div>

      <Separator />

      <div className="flex w-full flex-col gap-8 pb-6">
        {/* Speech-to-Text Section */}
        <div className="flex w-full max-w-[960px] flex-col gap-3">
          <div className="flex flex-col">
            <Text as="p" mainContentEmphasis text04>
              Speech to Text
            </Text>
            <Text as="p" secondaryBody text03>
              Select a model to transcribe speech to text in chats.
            </Text>
          </div>

          {sttActivationError && (
            <Callout type="danger" title="Unable to update STT provider">
              {sttActivationError}
            </Callout>
          )}

          {!hasActiveSTTProvider && (
            <div
              className="flex items-start rounded-16 border p-2"
              style={{
                backgroundColor: "var(--status-info-00)",
                borderColor: "var(--status-info-02)",
              }}
            >
              <div className="flex items-start gap-1 p-2">
                <div
                  className="flex size-5 items-center justify-center rounded-full p-0.5"
                  style={{
                    backgroundColor: "var(--status-info-01)",
                  }}
                >
                  <div style={{ color: "var(--status-text-info-05)" }}>
                    <InfoIcon size={16} />
                  </div>
                </div>
                <Text as="p" className="flex-1 px-0.5" mainUiBody text04>
                  Connect a speech to text provider to use in chat.
                </Text>
              </div>
            </div>
          )}

          <div className="flex flex-col gap-2">
            {STT_MODELS.map((model) => renderModelCard({ model, mode: "stt" }))}
          </div>
        </div>

        {/* Text-to-Speech Section */}
        <div className="flex w-full max-w-[960px] flex-col gap-3">
          <div className="flex flex-col">
            <Text as="p" mainContentEmphasis text04>
              Text to Speech
            </Text>
            <Text as="p" secondaryBody text03>
              Select a model to speak out chat responses.
            </Text>
          </div>

          {ttsActivationError && (
            <Callout type="danger" title="Unable to update TTS provider">
              {ttsActivationError}
            </Callout>
          )}

          {!hasActiveTTSProvider && (
            <div
              className="flex items-start rounded-16 border p-2"
              style={{
                backgroundColor: "var(--status-info-00)",
                borderColor: "var(--status-info-02)",
              }}
            >
              <div className="flex items-start gap-1 p-2">
                <div
                  className="flex size-5 items-center justify-center rounded-full p-0.5"
                  style={{
                    backgroundColor: "var(--status-info-01)",
                  }}
                >
                  <div style={{ color: "var(--status-text-info-05)" }}>
                    <InfoIcon size={16} />
                  </div>
                </div>
                <Text as="p" className="flex-1 px-0.5" mainUiBody text04>
                  Connect a text to speech provider to use in chat.
                </Text>
              </div>
            </div>
          )}

          <div className="flex flex-col gap-4">
            {TTS_PROVIDER_GROUPS.map((group) => (
              <div key={group.providerType} className="flex flex-col gap-2">
                <Text as="p" secondaryBody text03 className="px-0.5">
                  {group.providerLabel}
                </Text>
                <div className="flex flex-col gap-2">
                  {group.models.map((model) =>
                    renderModelCard({ model, mode: "tts" })
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

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
    </>
  );
}
