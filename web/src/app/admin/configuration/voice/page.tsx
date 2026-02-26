"use client";

import { useMemo, useState } from "react";
import { AdminPageTitle } from "@/components/admin/Title";
import { InfoIcon } from "@/components/icons/icons";
import Text from "@/refresh-components/texts/Text";
import Separator from "@/refresh-components/Separator";
import useSWR from "swr";
import { errorHandlingFetcher, FetchError } from "@/lib/fetcher";
import { ThreeDotsLoader } from "@/components/Loading";
import { Callout } from "@/components/ui/callout";
import Button from "@/refresh-components/buttons/Button";
import { Button as OpalButton } from "@opal/components";
import { cn } from "@/lib/utils";
import {
  SvgArrowExchange,
  SvgArrowRightCircle,
  SvgCheckSquare,
  SvgEdit,
  SvgMicrophone,
  SvgOpenai,
  SvgX,
} from "@opal/icons";
import { AzureIcon } from "@/components/icons/icons";
import VoiceProviderSetupModal from "./VoiceProviderSetupModal";

const VOICE_PROVIDERS_URL = "/api/admin/voice/providers";

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

interface ProviderDetails {
  label: string;
  subtitle: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  supportsSTT: boolean;
  supportsTTS: boolean;
}

const PROVIDER_DETAILS: Record<string, ProviderDetails> = {
  openai: {
    label: "OpenAI",
    subtitle: "Whisper for STT, TTS-1/TTS-1-HD for speech synthesis",
    icon: SvgOpenai,
    supportsSTT: true,
    supportsTTS: true,
  },
  azure: {
    label: "Azure Speech Services",
    subtitle: "Microsoft Azure Speech-to-Text and Text-to-Speech",
    icon: AzureIcon,
    supportsSTT: true,
    supportsTTS: true,
  },
  elevenlabs: {
    label: "ElevenLabs",
    subtitle: "High-quality voice synthesis",
    icon: SvgMicrophone,
    supportsSTT: true,
    supportsTTS: true,
  },
};

const PROVIDER_ORDER = ["openai", "azure", "elevenlabs"];

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
  const [sttActivationError, setSTTActivationError] = useState<string | null>(
    null
  );
  const [ttsActivationError, setTTSActivationError] = useState<string | null>(
    null
  );
  const [hoveredButtonKey, setHoveredButtonKey] = useState<string | null>(null);

  const {
    data: providers,
    error,
    isLoading,
    mutate,
  } = useSWR<VoiceProviderView[]>(VOICE_PROVIDERS_URL, errorHandlingFetcher);

  const handleConnect = (providerType: string, mode: ProviderMode) => {
    setSelectedProvider(providerType);
    setEditingProvider(null);
    setModalMode(mode);
    setModalOpen(true);
    setSTTActivationError(null);
    setTTSActivationError(null);
  };

  const handleEdit = (provider: VoiceProviderView, mode: ProviderMode) => {
    setSelectedProvider(provider.provider_type);
    setEditingProvider(provider);
    setModalMode(mode);
    setModalOpen(true);
  };

  const handleSetDefault = async (providerId: number, mode: ProviderMode) => {
    const setError =
      mode === "stt" ? setSTTActivationError : setTTSActivationError;
    setError(null);
    try {
      const response = await fetch(
        `${VOICE_PROVIDERS_URL}/${providerId}/activate-${mode}`,
        { method: "POST" }
      );
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
      const response = await fetch(
        `${VOICE_PROVIDERS_URL}/${providerId}/deactivate-${mode}`,
        { method: "POST" }
      );
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
  };

  const handleModalSuccess = () => {
    mutate();
    handleModalClose();
  };

  const isProviderConfigured = (provider?: VoiceProviderView): boolean => {
    return !!provider?.has_api_key;
  };

  const combinedProviders = useMemo(() => {
    const byType = new Map(
      (providers ?? []).map((p) => [p.provider_type, p] as const)
    );

    const ordered = PROVIDER_ORDER.map((providerType) => {
      const provider = byType.get(providerType);
      const details = PROVIDER_DETAILS[providerType];
      return {
        key: provider?.id ?? providerType,
        providerType,
        label: details?.label ?? providerType,
        subtitle: details?.subtitle ?? "",
        icon: details?.icon ?? SvgMicrophone,
        supportsSTT: details?.supportsSTT ?? false,
        supportsTTS: details?.supportsTTS ?? false,
        provider,
      };
    });

    return ordered;
  }, [providers]);

  const hasActiveSTTProvider =
    providers?.some((p) => p.is_default_stt) ?? false;
  const hasActiveTTSProvider =
    providers?.some((p) => p.is_default_tts) ?? false;
  const hasConfiguredProvider =
    providers?.some((p) => isProviderConfigured(p)) ?? false;

  const renderIcon = ({
    Icon,
    size = 16,
    isHighlighted = false,
  }: {
    Icon: React.ComponentType<{ size?: number; className?: string }>;
    size?: number;
    isHighlighted?: boolean;
  }) => {
    const containerSizeClass = size === 24 ? "size-7" : "size-5";

    return (
      <div
        className={cn(
          "flex items-center justify-center px-0.5 py-0 shrink-0 overflow-clip",
          containerSizeClass
        )}
      >
        <Icon
          size={size}
          className={
            isHighlighted ? "text-action-text-link-05" : "text-text-02"
          }
        />
      </div>
    );
  };

  const renderProviderCard = ({
    providerType,
    label,
    subtitle,
    icon: Icon,
    provider,
    mode,
    supportsMode,
  }: {
    providerType: string;
    label: string;
    subtitle: string;
    icon: React.ComponentType<{ size?: number; className?: string }>;
    provider?: VoiceProviderView;
    mode: ProviderMode;
    supportsMode: boolean;
  }) => {
    if (!supportsMode) return null;

    const isConfigured = isProviderConfigured(provider);
    const isActive =
      mode === "stt" ? provider?.is_default_stt : provider?.is_default_tts;
    const isHighlighted = isActive ?? false;
    const providerId = provider?.id;

    const buttonState = (() => {
      if (!provider || !isConfigured) {
        return {
          label: "Connect",
          disabled: false,
          icon: "arrow" as const,
          onClick: () => handleConnect(providerType, mode),
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
          ? () => handleSetDefault(providerId, mode)
          : undefined,
      };
    })();

    const buttonKey = `${mode}-${providerType}`;
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
        key={`${mode}-${providerType}`}
        onClick={isCardClickable ? handleCardClick : undefined}
        className={cn(
          "flex items-start justify-between gap-3 rounded-16 border p-1 bg-background-neutral-00",
          isHighlighted ? "border-action-link-05" : "border-border-01",
          isCardClickable &&
            "cursor-pointer hover:bg-background-tint-01 transition-colors"
        )}
      >
        <div className="flex flex-1 items-start gap-1 px-2 py-1">
          {renderIcon({
            Icon,
            size: 16,
            isHighlighted,
          })}
          <div className="flex flex-col gap-0.5">
            <Text as="p" mainUiAction text05>
              {label}
            </Text>
            <Text as="p" secondaryBody text03>
              {subtitle}
            </Text>
          </div>
        </div>
        <div className="flex items-center justify-end gap-2">
          {isConfigured && (
            <OpalButton
              icon={SvgEdit}
              tooltip="Edit"
              prominence="tertiary"
              size="sm"
              onClick={() => {
                if (provider) handleEdit(provider, mode);
              }}
              aria-label={`Edit ${label}`}
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
      <AdminPageTitle icon={SvgMicrophone} title="Voice" />
      <div className="pt-4 pb-4">
        <Text as="p" className="text-text-dark">
          Configure voice providers for Speech-to-Text (STT) and Text-to-Speech
          (TTS) capabilities.
        </Text>
      </div>

      <Separator />

      <div className="flex w-full flex-col gap-8 pb-6">
        {/* Speech-to-Text Section */}
        <div className="flex w-full max-w-[960px] flex-col gap-3">
          <div className="flex flex-col gap-0.5">
            <Text as="p" mainContentEmphasis text05>
              Speech-to-Text
            </Text>
            <Text
              as="p"
              className="flex items-start gap-[2px] self-stretch text-text-03"
              secondaryBody
              text03
            >
              Transcribe voice input from users into text.
            </Text>
          </div>

          {sttActivationError && (
            <Callout type="danger" title="Unable to update STT provider">
              {sttActivationError}
            </Callout>
          )}

          {!hasActiveSTTProvider && (
            <div
              className="flex items-start rounded-16 border p-1"
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
                  {hasConfiguredProvider
                    ? "Select a provider to enable speech-to-text."
                    : "Connect a provider to enable speech-to-text."}
                </Text>
              </div>
            </div>
          )}

          <div className="flex flex-col gap-2">
            {combinedProviders.map(
              ({
                providerType,
                label,
                subtitle,
                icon,
                supportsSTT,
                provider,
              }) =>
                renderProviderCard({
                  providerType,
                  label,
                  subtitle,
                  icon,
                  provider,
                  mode: "stt",
                  supportsMode: supportsSTT,
                })
            )}
          </div>
        </div>

        {/* Text-to-Speech Section */}
        <div className="flex w-full max-w-[960px] flex-col gap-3">
          <div className="flex flex-col gap-0.5">
            <Text as="p" mainContentEmphasis text05>
              Text-to-Speech
            </Text>
            <Text
              as="p"
              className="flex items-start gap-[2px] self-stretch text-text-03"
              secondaryBody
              text03
            >
              Read responses back to users with natural-sounding voices.
            </Text>
          </div>

          {ttsActivationError && (
            <Callout type="danger" title="Unable to update TTS provider">
              {ttsActivationError}
            </Callout>
          )}

          {!hasActiveTTSProvider && (
            <div
              className="flex items-start rounded-16 border p-1"
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
                  {hasConfiguredProvider
                    ? "Select a provider to enable text-to-speech."
                    : "Connect a provider to enable text-to-speech."}
                </Text>
              </div>
            </div>
          )}

          <div className="flex flex-col gap-2">
            {combinedProviders.map(
              ({
                providerType,
                label,
                subtitle,
                icon,
                supportsTTS,
                provider,
              }) =>
                renderProviderCard({
                  providerType,
                  label,
                  subtitle,
                  icon,
                  provider,
                  mode: "tts",
                  supportsMode: supportsTTS,
                })
            )}
          </div>
        </div>
      </div>

      {modalOpen && selectedProvider && (
        <VoiceProviderSetupModal
          providerType={selectedProvider}
          existingProvider={editingProvider}
          mode={modalMode}
          onClose={handleModalClose}
          onSuccess={handleModalSuccess}
        />
      )}
    </>
  );
}
