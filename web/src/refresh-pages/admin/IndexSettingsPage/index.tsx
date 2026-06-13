"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Formik } from "formik";
import { markdown } from "@opal/utils";
import { useRouter } from "next/navigation";
import { mutate } from "swr";
import { ThreeDotsLoader } from "@/components/Loading";
import { SWR_KEYS } from "@/lib/swr-keys";
import { Content, IllustrationContent } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import { SettingsLayouts } from "@opal/layouts";
import * as GeneralLayouts from "@/layouts/general-layouts";
import { InputHorizontal } from "@opal/layouts";
import {
  Button,
  Card,
  Divider,
  InputTypeIn,
  LinkButton,
  MessageCard,
  OpenButton,
  Popover,
  SelectCard,
  Spacer,
  Switch,
  Tabs,
  Text,
} from "@opal/components";
import {
  SvgArrowExchange,
  SvgCheckSquare,
  SvgClock,
  SvgCloud,
  SvgEmpty,
  SvgExternalLink,
  SvgFold,
  SvgPlusCircle,
  SvgRevert,
  SvgServer,
  SvgSettings,
  SvgSlowTime,
  SvgUnplug,
  SvgVector,
} from "@opal/icons";
import SwitchField from "@/refresh-components/form/SwitchField";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { Disabled } from "@opal/core";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import {
  EmbeddingProviderName,
  SwitchoverType,
  type ConfiguredEmbeddingProvider,
  type EmbeddingModel,
  type EmbeddingModelRequest,
  type EmbeddingModelState,
  type EmbeddingProvider,
} from "@/lib/indexing/interfaces";
import {
  CLOUD_BASED_PROVIDERS,
  CUSTOM_PROVIDER,
  SELF_HOSTED_PROVIDERS,
  findProvider,
  findRegistryModel,
  isCloudBased,
  MAX_IMAGE_SIZE_OPTIONS,
  resolveProviderName,
} from "@/lib/indexing";
import {
  saveAdminSettings,
  cancelNewEmbedding,
  disconnectEmbeddingProvider,
  setNewSearchSettings,
} from "@/lib/indexing/svc";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import { ContentAction } from "@opal/layouts";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import { useSettingsContext } from "@/providers/SettingsProvider";
import { Settings } from "@/interfaces/settings";
import { toast } from "@/hooks/useToast";
import {
  useConfiguredEmbeddingProviders,
  useCurrentEmbeddingModel,
  useCurrentSearchSettings,
  useSecondarySearchSettings,
} from "@/hooks/useSearchSettings";
import { useLlmDefaults } from "@/hooks/useLanguageModels";
import useFilter from "@/hooks/useFilter";
import ModelListContent from "@/refresh-components/popovers/ModelListContent";
import type { LLMOption } from "@/refresh-components/popovers/interfaces";
import type { RichStr } from "@opal/types";
import { getModelIcon } from "@/lib/languageModels";
import { ProviderCredentialsModal } from "@/refresh-pages/admin/IndexSettingsPage/modals";

const route = ADMIN_ROUTES.INDEX_SETTINGS;

const MODEL_TAB_CLOUD = "cloud-based";
const MODEL_TAB_SELF = "self-hosted";
const CLOUD_TOOLTIP = "此设置由 Glomi Cloud 管理。";

/**
 * Wrapper that disables its children when either:
 * 1. The app is running on Glomi Cloud (`NEXT_PUBLIC_CLOUD_ENABLED`), or
 * 2. A local `disabled` condition is true (e.g. a parent toggle is off).
 */
interface CloudDisabledProps {
  disabled?: boolean;
  tooltip?: string | RichStr;
  children: React.ReactNode;
}
function CloudDisabled({
  disabled = false,
  tooltip: tooltipProp,
  children,
}: CloudDisabledProps) {
  const isDisabled = NEXT_PUBLIC_CLOUD_ENABLED || disabled;
  const tooltip = NEXT_PUBLIC_CLOUD_ENABLED ? CLOUD_TOOLTIP : tooltipProp;

  return (
    <Disabled disabled={isDisabled} tooltip={tooltip} tooltipSide="right">
      {children}
    </Disabled>
  );
}

interface EmbeddingProviderInfoProps {
  providerName: EmbeddingProviderName;
}

function EmbeddingProviderInfo({ providerName }: EmbeddingProviderInfoProps) {
  if (!isCloudBased(providerName)) {
    return (
      <Content
        icon={SvgServer}
        title="自托管"
        sizePreset="secondary"
        variant="body"
        color="muted"
        width="fit"
      />
    );
  }

  const provider = findProvider(providerName);

  return (
    <>
      <Content
        icon={SvgCloud}
        title="云服务商"
        sizePreset="secondary"
        variant="body"
        color="muted"
        width="fit"
      />
      {provider.costslink && (
        <LinkButton href={provider.costslink} target="_blank">
          价格
        </LinkButton>
      )}
      {provider.docsLink && (
        <LinkButton href={provider.docsLink} target="_blank">
          文档
        </LinkButton>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Contextual RAG LLM picker
// ---------------------------------------------------------------------------

interface LlmPickerProps {
  modelConfigurationId?: number | null;
  modelName?: string | null;
  providerName?: string | null;
  onChange: (next: {
    modelConfigurationId: number | null;
    modelName: string;
    providerName: string | null;
  }) => void;
  disabled?: boolean;
  /**
   * When true, restricts the popover to vision-capable models (those with
   * `supports_image_input === true`). Used by the Captioning LLM picker;
   * leave unset for any-model use cases like Contextual Retrieval.
   */
  requiresImageInput?: boolean;
}

/**
 * Single-select LLM picker bound to external state, unlike `LLMPopover`
 * which is wired to `LlmManager.currentLlm` and would mutate the user's
 * default chat model on select. Reuses the same popover primitives
 * (`Popover`, `OpenButton`, `ModelListContent`) for visual parity.
 *
 * Supports two selection modes:
 * - By ID: pass `modelConfigurationId` — preferred when the FK integer is
 *   available (e.g. contextual RAG, where the backend now stores the integer).
 * - By name: pass `modelName` + `providerName` — used for the captioning LLM
 *   which is keyed by the global vision default rather than a stored FK.
 *
 * `onChange` always emits all three fields so callers can destructure what
 * they need.
 */
function LlmPicker({
  modelConfigurationId,
  modelName,
  providerName,
  onChange,
  disabled,
  requiresImageInput,
}: LlmPickerProps) {
  const [open, setOpen] = useState(false);
  const { llmProviders, isLoading } = useLlmDefaults();

  const isSelected = useCallback(
    (option: LLMOption) => {
      if (modelConfigurationId != null) {
        return option.modelConfigurationId === modelConfigurationId;
      }
      return option.modelName === modelName && option.name === providerName;
    },
    [modelConfigurationId, modelName, providerName]
  );

  const handleSelect = useCallback(
    (option: LLMOption) => {
      onChange({
        modelConfigurationId: option.modelConfigurationId ?? null,
        modelName: option.modelName,
        providerName: option.name ?? null,
      });
      setOpen(false);
    },
    [onChange]
  );

  const { displayName, providerType } = useMemo(() => {
    if (!llmProviders) {
      return { displayName: null as string | null, providerType: null };
    }
    if (modelConfigurationId != null) {
      for (const p of llmProviders) {
        const cfg = p.model_configurations.find(
          (m) => m.id === modelConfigurationId
        );
        if (cfg) {
          return {
            displayName: cfg.display_name || cfg.name,
            providerType: p.provider,
          };
        }
      }
      return { displayName: null, providerType: null };
    }
    if (!modelName || !providerName) {
      return { displayName: null, providerType: null };
    }
    for (const p of llmProviders) {
      if (p.name !== providerName) continue;
      const cfg = p.model_configurations.find((m) => m.name === modelName);
      if (cfg) {
        return {
          displayName: cfg.display_name || cfg.name,
          providerType: p.provider,
        };
      }
    }
    return { displayName: modelName, providerType: null };
  }, [llmProviders, modelConfigurationId, modelName, providerName]);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild disabled={disabled}>
        <OpenButton
          disabled={disabled}
          icon={
            providerType
              ? getModelIcon(providerType, modelName ?? "")
              : undefined
          }
        >
          {displayName ?? "选择模型"}
        </OpenButton>
      </Popover.Trigger>
      <Popover.Content side="top" align="end" width="xl">
        <ModelListContent
          llmProviders={llmProviders}
          isLoading={isLoading}
          onSelect={handleSelect}
          isSelected={isSelected}
          requiresImageInput={requiresImageInput}
        />
      </Popover.Content>
    </Popover>
  );
}

// ---------------------------------------------------------------------------
// Embedding model picker components
// ---------------------------------------------------------------------------

interface ProviderGroupProps {
  provider: EmbeddingProvider;
  currentModelName?: string;
  selectedModelName?: string;
  isCloud?: boolean;
  existingCredentials?: ConfiguredEmbeddingProvider;
  /**
   * Camel-cased spec of the active embedding model when it belongs to THIS
   * provider — passed straight through to `ProviderCredentialsModal` so
   * `LiteLLMProviderModal` can preload its model-spec fields on edit.
   */
  existingModel?: EmbeddingModel;
  /**
   * Stage a model into the parent form. `customModel` is populated only when
   * the provider has no pre-registered models and the user defined the spec in
   * the connect modal (LiteLLM / Azure) — the parent uses it to set both
   * `model_name` and `custom_model`, and to remember this cloud provider as the
   * staged model's owner so submit doesn't misresolve it as self-hosted.
   */
  onSelectModel: (
    modelName: string,
    customModel?: EmbeddingModelRequest
  ) => void;
  onDeselectModel: () => void;
}

function ProviderGroup({
  provider,
  currentModelName,
  selectedModelName,
  isCloud = false,
  existingCredentials,
  existingModel,
  onSelectModel,
  onDeselectModel,
}: ProviderGroupProps) {
  const models = provider.embeddingModels;
  const isConfigured = isCloud ? !!existingCredentials : true;
  const disconnectModal = useCreateModal();
  const connectModal = useCreateModal();
  const editCredentialsModal = useCreateModal();
  const providerCreationModal = useCreateModal();
  const [pendingConnectModel, setPendingConnectModel] =
    useState<EmbeddingModel | null>(null);
  const providerGroupContainsCurrentModelName = models.some(
    (m) => m.modelName === currentModelName
  );

  const handleDisconnect = useCallback(async () => {
    if (!isCloud) return;
    try {
      await disconnectEmbeddingProvider(provider.providerName);
      toast.success(`已断开 ${provider.displayName}`);
      await mutate(SWR_KEYS.embeddingProviders);
      onDeselectModel();
      disconnectModal.toggle(false);
    } catch {
      toast.error(`断开 ${provider.displayName} 失败`);
    }
  }, [
    isCloud,
    provider.providerName,
    provider.displayName,
    onDeselectModel,
    disconnectModal,
  ]);

  const getModelState = useCallback(
    (model: EmbeddingModel): EmbeddingModelState => {
      if (isCloud && !isConfigured) return "unconnected";
      if (model.modelName === selectedModelName) return "selected";
      if (model.modelName === currentModelName) return "current";
      return "connected";
    },
    [isCloud, isConfigured, selectedModelName, currentModelName]
  );

  const handleModelSelect = useCallback(
    (model: EmbeddingModel) => {
      if (provider.deprecated) return;
      const state = getModelState(model);

      if (state === "selected" || state === "current") {
        onDeselectModel();
        return;
      }

      if (state === "unconnected" && isCloud) {
        setPendingConnectModel(model);
        connectModal.toggle(true);
        return;
      }

      onSelectModel(model.modelName);
    },
    [
      getModelState,
      onSelectModel,
      onDeselectModel,
      connectModal,
      provider.deprecated,
      isCloud,
      setPendingConnectModel,
    ]
  );

  return (
    <>
      {isCloud && (
        <>
          <disconnectModal.Provider>
            <ConfirmationModalLayout
              icon={SvgUnplug}
              title={`断开 ${provider.displayName}`}
              submit={
                <Button variant="danger" onClick={handleDisconnect}>
                  断开
                </Button>
              }
            >
              <Text font="main-ui-body" color="text-03" as="p">
                {markdown(
                  `这会断开服务商 **${provider.displayName}** 的全部嵌入模型。`
                )}
              </Text>
            </ConfirmationModalLayout>
          </disconnectModal.Provider>

          <connectModal.Provider>
            <ProviderCredentialsModal
              provider={provider}
              onSubmit={async (customModel) => {
                await mutate(SWR_KEYS.embeddingProviders);
                if (pendingConnectModel) {
                  onSelectModel(pendingConnectModel.modelName, customModel);
                  setPendingConnectModel(null);
                }
                connectModal.toggle(false);
              }}
            />
          </connectModal.Provider>

          <editCredentialsModal.Provider>
            <ProviderCredentialsModal
              provider={provider}
              existingCredentials={existingCredentials}
              existingModel={existingModel}
              onSubmit={async () => {
                await mutate(SWR_KEYS.embeddingProviders);
                editCredentialsModal.toggle(false);
              }}
            />
          </editCredentialsModal.Provider>
        </>
      )}

      <providerCreationModal.Provider>
        <ProviderCredentialsModal
          provider={provider}
          onSubmit={async (customModel) => {
            await mutate(SWR_KEYS.embeddingProviders);
            // Providers with no pre-registered models (LiteLLM / Azure) define
            // their model spec right here — stage it so the user can apply it.
            // Without this the provider row is saved but the model is dropped,
            // so no search-settings row is ever created.
            if (customModel?.modelName) {
              onSelectModel(customModel.modelName, customModel);
            }
            providerCreationModal.toggle(false);
          }}
        />
      </providerCreationModal.Provider>

      <GeneralLayouts.Section gap={0.25}>
        <div className="px-1 pt-1 w-full h-(--height-line-h1-headline)">
          <GeneralLayouts.Section flexDirection="row" gap={0}>
            <Spacer orientation="horizontal" rem={0.675} />
            <div className="flex flex-row justify-between items-center w-full py-1">
              <Content
                icon={provider.icon}
                title={
                  provider.docsLink
                    ? markdown(
                        `[${provider.displayName}](${provider.docsLink})`
                      )
                    : provider.displayName
                }
                suffix={provider.deprecated ? "（已弃用）" : undefined}
                sizePreset="secondary"
              />

              {isCloud && isConfigured ? (
                <GeneralLayouts.Section
                  flexDirection="row"
                  gap={0.25}
                  width="fit"
                >
                  <Button
                    icon={SvgUnplug}
                    prominence="tertiary"
                    size="sm"
                    disabled={providerGroupContainsCurrentModelName}
                    tooltip={
                      providerGroupContainsCurrentModelName
                        ? "无法断开当前默认嵌入模型。请先选择新模型。"
                        : undefined
                    }
                    onClick={() => disconnectModal.toggle(true)}
                  />
                  <Button
                    icon={SvgSettings}
                    prominence="tertiary"
                    size="sm"
                    aria-label="编辑凭据"
                    tooltip="编辑凭据"
                    onClick={() => editCredentialsModal.toggle(true)}
                  />
                  <Spacer orientation="horizontal" rem={0.25} />
                </GeneralLayouts.Section>
              ) : undefined}
            </div>
          </GeneralLayouts.Section>
        </div>

        {models.length === 0 ? (
          <SelectCard
            state="filled"
            rounding="md"
            padding="sm"
            onClick={() => providerCreationModal.toggle(true)}
          >
            <ContentAction
              title={`为 ${provider.displayName} 嵌入服务商添加配置。`}
              sizePreset="secondary"
              variant="body"
              color="muted"
              padding="md"
              rightChildren={
                <Button
                  prominence="tertiary"
                  rightIcon={SvgPlusCircle}
                  onClick={() => providerCreationModal.toggle(true)}
                >
                  添加配置
                </Button>
              }
              center
            />
          </SelectCard>
        ) : (
          models.map((model) => {
            const state = getModelState(model);
            const isPrioritized =
              state === "selected" ||
              (state === "current" && !selectedModelName);
            return (
              <EmbeddingModelCard
                key={model.modelName}
                model={model}
                provider={provider}
                modelState={state}
                cardState={isPrioritized ? "selected" : "filled"}
                onSelect={() => handleModelSelect(model)}
              />
            );
          })
        )}
      </GeneralLayouts.Section>
    </>
  );
}

interface EmbeddingModelCardProps {
  provider: EmbeddingProvider;
  model: EmbeddingModel;
  modelState: EmbeddingModelState;
  cardState: "filled" | "selected";
  onSelect?: () => void;
}

function EmbeddingModelCard({
  provider,
  model,
  modelState,
  cardState,
  onSelect,
}: EmbeddingModelCardProps) {
  const topRightButton = (() => {
    switch (modelState) {
      case "unconnected":
        return (
          <Button
            prominence="tertiary"
            rightIcon={SvgArrowExchange}
            onClick={onSelect}
            disabled={provider.deprecated}
            tooltip={
              provider.deprecated
                ? "此嵌入模型已弃用，无法连接。"
                : undefined
            }
          >
            连接
          </Button>
        );
      case "connected":
        return (
          <Button
            prominence="tertiary"
            onClick={onSelect}
            disabled={provider.deprecated}
            tooltip={
              provider.deprecated
                ? "此嵌入模型已弃用，无法选择。"
                : undefined
            }
          >
            选择模型
          </Button>
        );
      case "current":
        return (
          <Button
            variant="action"
            prominence="tertiary"
            rightIcon={SvgCheckSquare}
            onClick={onSelect}
          >
            当前模型
          </Button>
        );
      case "selected":
        return (
          <Button
            variant="action"
            prominence="tertiary"
            rightIcon={SvgCheckSquare}
            onClick={onSelect}
          >
            已选择
          </Button>
        );
    }
  })();

  const isClickable =
    !provider.deprecated &&
    (modelState === "unconnected" ||
      modelState === "connected" ||
      modelState === "current" ||
      modelState === "selected");

  return (
    <SelectCard
      state={cardState}
      rounding="md"
      padding="xs"
      onClick={isClickable ? onSelect : undefined}
    >
      <GeneralLayouts.Section flexDirection="row" alignItems="start">
        <GeneralLayouts.Section gap={0} padding={0.5} alignItems="start">
          <Content
            icon={provider.icon}
            title={model.modelName}
            description={model.description}
            sizePreset="main-ui"
            variant="section"
          />
          <div className="flex flex-row px-6 pt-2 gap-4">
            <EmbeddingProviderInfo providerName={provider.providerName} />
          </div>
        </GeneralLayouts.Section>
        {topRightButton && <div className="shrink-0">{topRightButton}</div>}
      </GeneralLayouts.Section>
    </SelectCard>
  );
}

interface IndexSettingsFormValues {
  model_name: string;
  /**
   * Populated when the staged model came from the "Add Custom Model" modal
   * — i.e. it's not in `CLOUD_BASED_PROVIDERS` / `SELF_HOSTED_PROVIDERS`.
   * The submit path uses this directly instead of looking the name up in
   * the static registry. Cleared whenever the user selects a registered
   * model.
   */
  custom_model: EmbeddingModel | null;
  /**
   * The cloud provider that owns a staged `custom_model` (LiteLLM / Azure).
   * Those providers have no pre-registered models, so `resolveProviderName`
   * can't recover their identity from the model name alone and would fall
   * through to `CUSTOM` (self-hosted) — sending `provider_type=null` to the
   * backend and bypassing the cloud credentials. Carrying it explicitly keeps
   * the staged model bound to its provider. `null` for registered or
   * self-hosted models, where name-based resolution is sufficient.
   */
  custom_model_provider: EmbeddingProviderName | null;
  enable_contextual_rag: boolean;
  contextual_rag_model_configuration_id: number | null;
}

export default function IndexSettingsPage() {
  const router = useRouter();
  const settings = useSettingsContext();
  const editModal = useCreateModal();
  const [viewAllModelsOpen, setViewAllModelsOpen] = useState(false);
  const [activeModelTab, setActiveModelTab] = useState(MODEL_TAB_CLOUD);
  const [switchoverType, setSwitchoverType] = useState<SwitchoverType>(
    SwitchoverType.REINDEX
  );

  const allModels = useMemo(
    () => [...CLOUD_BASED_PROVIDERS, ...SELF_HOSTED_PROVIDERS],
    []
  );

  const {
    query,
    setQuery,
    filtered: filteredProviders,
  } = useFilter(
    allModels,
    (embeddingProvider) =>
      `${embeddingProvider.displayName} ${embeddingProvider.embeddingModels
        .map((embeddingModel) => embeddingModel.modelName)
        .join(" ")}`
  );

  const { filteredCloudProviders, filteredSelfHostedProviders } =
    useMemo(() => {
      const matched = new Set(filteredProviders);
      return {
        filteredCloudProviders: CLOUD_BASED_PROVIDERS.filter((p) =>
          matched.has(p)
        ),
        filteredSelfHostedProviders: SELF_HOSTED_PROVIDERS.filter((p) =>
          matched.has(p)
        ),
      };
    }, [filteredProviders]);

  const saveSettings = useCallback(
    async (updates: Partial<Settings>) => {
      if (!settings.settings) return;

      try {
        await saveAdminSettings({ ...settings.settings, ...updates });
        router.refresh();
        await mutate(SWR_KEYS.settings);
        toast.success("设置已更新");
      } catch {
        toast.error("设置更新失败");
      }
    },
    [settings.settings, router]
  );

  const imageProcessingEnabled =
    settings.settings.image_extraction_and_analysis_enabled ?? false;

  const { data: secondarySearchSettings } = useSecondarySearchSettings();
  const isReindexing = !!secondarySearchSettings;

  // When a migration finishes, the fast poll on the current settings stops in
  // the same render — revalidate once so the new model shows as current.
  const wasReindexingRef = useRef(false);
  useEffect(() => {
    if (wasReindexingRef.current && !isReindexing) {
      mutate(SWR_KEYS.currentSearchSettings);
    }
    wasReindexingRef.current = isReindexing;
  }, [isReindexing]);

  // Shares the current-settings SWR key, which useCurrentSearchSettings
  // below already polls while reindexing — one timer drives both hooks.
  const { data: currentEmbeddingModel, isLoading: isLoadingCurrentModel } =
    useCurrentEmbeddingModel();

  /**
   * Camel-cased view of the active embedding model for modal preload.
   * Consumed by `LiteLLMProviderModal` and `CustomSelfHostedModal`.
   * See `ProviderModalProps.existingModel`.
   */
  const currentEmbeddingModelSpec: EmbeddingModel | null = useMemo(() => {
    if (!currentEmbeddingModel) return null;
    return {
      modelName: currentEmbeddingModel.model_name,
      modelDim: currentEmbeddingModel.model_dim,
      normalize: currentEmbeddingModel.normalize,
      queryPrefix: currentEmbeddingModel.query_prefix,
      passagePrefix: currentEmbeddingModel.passage_prefix,
      description: "",
    };
  }, [currentEmbeddingModel]);

  const currentProviderName = currentEmbeddingModel
    ? resolveProviderName(
        currentEmbeddingModel.model_name,
        currentEmbeddingModel.provider_type
      )
    : null;
  const currentProvider = currentProviderName
    ? findProvider(currentProviderName)
    : null;
  const isCurrentCloudBased = currentProviderName
    ? isCloudBased(currentProviderName)
    : false;

  const { data: searchSettings, isLoading: isLoadingSearchSettings } =
    useCurrentSearchSettings({ pollIntervalMs: isReindexing ? 5000 : 0 });
  const { data: configuredProvidersList } = useConfiguredEmbeddingProviders();
  const configuredProviders = useMemo(
    () =>
      new Map((configuredProvidersList ?? []).map((p) => [p.provider_type, p])),
    [configuredProvidersList]
  );
  const cancelReindexModal = useCreateModal();
  const customModelModal = useCreateModal();

  const {
    llmProviders,
    hasAnyLlm,
    hasAnyVisionLlm,
    defaultLlm,
    defaultVision,
    isLoading: isLoadingLlmProviders,
  } = useLlmDefaults();

  /**
   * Persist a new default vision model. Glomi AI routes all image-captioning
   * calls through `get_default_llm_with_vision()` (`backend/onyx/llm/factory.py`),
   * which reads `default_vision` — so writing here switches the model the
   * indexer uses for new captions. Existing captions stay baked into the
   * embeddings of already-indexed documents.
   */
  const handleCaptioningModelChange = useCallback(
    async ({
      modelName,
      providerName,
    }: {
      modelName: string;
      providerName: string | null;
    }) => {
      const provider = llmProviders?.find((p) => p.name === providerName);
      if (!provider) {
        toast.error("无法识别服务商");
        return;
      }
      try {
        const response = await fetch("/api/admin/llm/default-vision", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            provider_id: provider.id,
            model_name: modelName,
          }),
        });
        if (!response.ok) {
          throw new Error(
            (await response.json()).detail ?? "图片描述 LLM 更新失败"
          );
        }
        await mutate(SWR_KEYS.llmProviders);
        toast.success("图片描述 LLM 已更新");
      } catch (error) {
        toast.error(
          error instanceof Error ? error.message : "发生未知错误"
        );
      }
    },
    [llmProviders]
  );

  const initialFormValues: IndexSettingsFormValues = useMemo(
    () => ({
      model_name: currentEmbeddingModel?.model_name ?? "",
      custom_model: null,
      custom_model_provider: null,
      enable_contextual_rag: searchSettings?.enable_contextual_rag ?? false,
      contextual_rag_model_configuration_id:
        searchSettings?.contextual_rag_model_configuration_id ?? null,
    }),
    [currentEmbeddingModel, searchSettings]
  );

  const handleCancelReindex = useCallback(async () => {
    const response = await cancelNewEmbedding();
    if (!response.ok) {
      toast.error("取消重新索引失败");
      return;
    }
    cancelReindexModal.toggle(false);
    toast.success("重新索引已取消");
    await Promise.all([
      mutate(SWR_KEYS.currentSearchSettings),
      mutate(SWR_KEYS.secondarySearchSettings),
      mutate(SWR_KEYS.indexingStatus),
    ]);
  }, [cancelReindexModal]);

  if (
    isLoadingCurrentModel ||
    isLoadingSearchSettings ||
    isLoadingLlmProviders
  ) {
    return (
      <SettingsLayouts.Root>
        <SettingsLayouts.Header icon={route.icon} title={route.title} divider />
        <SettingsLayouts.Body>
          <ThreeDotsLoader />
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }

  return (
    <>
      {currentProvider && isCurrentCloudBased && (
        <editModal.Provider>
          <ProviderCredentialsModal
            provider={currentProvider}
            existingCredentials={configuredProviders?.get(
              currentProvider.providerName
            )}
            existingModel={currentEmbeddingModelSpec ?? undefined}
            onSubmit={async () => {
              await mutate(SWR_KEYS.embeddingProviders);
              editModal.toggle(false);
            }}
          />
        </editModal.Provider>
      )}

      <cancelReindexModal.Provider>
        <ConfirmationModalLayout
          icon={SvgRevert}
          title="取消重新索引"
          submit={
            <Button variant="danger" onClick={handleCancelReindex}>
              取消
            </Button>
          }
        >
          <Text font="main-ui-body" color="text-03" as="p">
            取消后会回退到之前的嵌入模型，所有重新索引进度都会丢失。
          </Text>
        </ConfirmationModalLayout>
      </cancelReindexModal.Provider>

      <SettingsLayouts.Root>
        <SettingsLayouts.Header
          icon={route.icon}
          title={route.title}
          description="配置文档如何被索引、嵌入，并用于搜索和检索。"
          divider
        />

        <SettingsLayouts.Body>
          <Formik<IndexSettingsFormValues>
            enableReinitialize
            initialValues={initialFormValues}
            onSubmit={async (values) => {
              // Custom self-hosted models live outside the static registry,
              // so the form carries their spec (`modelDim`, `normalize`, etc.)
              // in `custom_model` for submission. The provider, however, is
              // ALWAYS resolved through `resolveProviderName` — see its NOTE
              // for why this is the single source of truth for provider
              // discrimination.
              const stagedModel =
                values.custom_model ?? findRegistryModel(values.model_name);
              if (!stagedModel) {
                toast.error("未找到所选模型");
                return;
              }
              // A staged custom model from a no-registry cloud provider
              // (LiteLLM / Azure) carries its owning provider explicitly;
              // otherwise fall back to resolving the provider from the model
              // name against the static registry.
              const providerName =
                values.custom_model_provider ??
                resolveProviderName(values.model_name, null);

              const response = await setNewSearchSettings({
                model: stagedModel,
                providerName,
                switchoverType,
                enableContextualRag: values.enable_contextual_rag,
                contextualRagModelConfigurationId: values.enable_contextual_rag
                  ? values.contextual_rag_model_configuration_id
                  : null,
              });

              if (!response.ok) {
                toast.error("应用设置失败");
                return;
              }

              toast.success("重新索引已开始");
              setSwitchoverType(SwitchoverType.REINDEX);
              await Promise.all([
                mutate(SWR_KEYS.currentSearchSettings),
                mutate(SWR_KEYS.secondarySearchSettings),
              ]);
            }}
          >
            {({ values, dirty, setFieldValue, resetForm, submitForm }) => {
              const isModelStaged =
                values.model_name !== initialFormValues.model_name &&
                !!values.model_name;
              const stagedModelName = isModelStaged ? values.model_name : null;
              const statusVariant = dirty ? "warning" : undefined;

              return (
                <>
                  <customModelModal.Provider>
                    <ProviderCredentialsModal
                      provider={CUSTOM_PROVIDER}
                      existingModel={
                        currentProviderName === EmbeddingProviderName.CUSTOM
                          ? (currentEmbeddingModelSpec ?? undefined)
                          : undefined
                      }
                      onSubmit={(customModel) => {
                        if (customModel) {
                          void setFieldValue(
                            "model_name",
                            customModel.modelName
                          );
                          void setFieldValue("custom_model", customModel);
                          // Self-hosted custom models resolve to CUSTOM by
                          // name — no cloud provider to bind.
                          void setFieldValue("custom_model_provider", null);
                        }
                        customModelModal.toggle(false);
                      }}
                    />
                  </customModelModal.Provider>

                  {isReindexing ? (
                    <MessageCard
                      variant="warning"
                      headerPadding="sm"
                      title="正在重新索引"
                      description={markdown(
                        `正在切换到 **${secondarySearchSettings?.model_name}**。现有文档正在重新嵌入，具体耗时取决于语料规模，可能需要数小时或数天。切换完成前，旧模型会继续服务查询。`
                      )}
                      bottomChildren={
                        <GeneralLayouts.Section
                          flexDirection="row"
                          gap={0.5}
                          justifyContent="end"
                          padding={0.5}
                        >
                          <Button
                            icon={SvgExternalLink}
                            href="/admin/indexing/status"
                          >
                            查看连接器
                          </Button>
                          <Button
                            variant="danger"
                            prominence="secondary"
                            onClick={() => cancelReindexModal.toggle(true)}
                          >
                            取消重新索引
                          </Button>
                        </GeneralLayouts.Section>
                      }
                    />
                  ) : (
                    !NEXT_PUBLIC_CLOUD_ENABLED && (
                      <MessageCard
                        variant={statusVariant}
                        headerPadding="sm"
                        title="更改需要完整重新索引。"
                        description={markdown(
                          "修改嵌入或检索设置后，需要对全部文档进行完整重新索引才能生效。具体耗时取决于语料规模，可能需要 **数小时或数天**。[了解更多](https://docs.glomi.ai/security/architecture/data_flows)"
                        )}
                        bottomChildren={
                          dirty ? (
                            <div className="flex flex-row items-end gap-4 p-2">
                              <div className="flex-1 min-w-0">
                                <InputSelect
                                  value={switchoverType}
                                  onValueChange={(v) =>
                                    setSwitchoverType(v as SwitchoverType)
                                  }
                                >
                                  <InputSelect.Trigger placeholder="选择切换策略" />
                                  <InputSelect.Content>
                                    <InputSelect.Item
                                      value={SwitchoverType.REINDEX}
                                      icon={SvgClock}
                                      wrapDescription
                                      description="最稳妥的选项。在全部连接器成功完成一次索引前，继续使用当前文档索引和现有设置。"
                                    >
                                      重新索引全部连接器后切换
                                    </InputSelect.Item>
                                    <InputSelect.Item
                                      value={SwitchoverType.ACTIVE_ONLY}
                                      icon={SvgSlowTime}
                                      wrapDescription
                                      description="在全部活跃连接器（未暂停/未删除）成功完成一次索引前，继续使用当前文档索引和现有设置。"
                                    >
                                      重新索引活跃连接器后切换
                                    </InputSelect.Item>
                                    <InputSelect.Item
                                      value={SwitchoverType.INSTANT}
                                      icon={SvgEmpty}
                                      wrapDescription
                                      description="立即清空当前文档索引并切换到新设置。需要重新索引全部连接器后，搜索索引才会重新填充。"
                                    >
                                      重新索引前立即切换
                                    </InputSelect.Item>
                                  </InputSelect.Content>
                                </InputSelect>
                              </div>
                              <div className="flex flex-row gap-2 shrink-0">
                                <Button
                                  prominence="secondary"
                                  onClick={() => {
                                    resetForm();
                                    setSwitchoverType(SwitchoverType.REINDEX);
                                  }}
                                >
                                  还原
                                </Button>
                                <Button onClick={() => void submitForm()}>
                                  应用并重新索引
                                </Button>
                              </div>
                            </div>
                          ) : undefined
                        }
                      />
                    )
                  )}

                  {/* ── Embedding Model ── */}
                  <GeneralLayouts.Section
                    gap={0.75}
                    height="fit"
                    alignItems="stretch"
                    justifyContent="start"
                  >
                    <Content
                      title="嵌入模型"
                      description="Glomi AI 使用这个模型对文档进行编码，用于搜索和检索。"
                      sizePreset="main-content"
                      variant="section"
                    />

                    {NEXT_PUBLIC_CLOUD_ENABLED ? (
                      <CloudDisabled>
                        <Card border="solid" rounding="lg" padding="sm">
                          <GeneralLayouts.Section padding={0.5}>
                            <Content
                              icon={SvgVector}
                              title="嵌入模型和设置由 Glomi Cloud 管理。"
                              sizePreset="main-ui"
                              variant="section"
                            />
                          </GeneralLayouts.Section>
                        </Card>
                      </CloudDisabled>
                    ) : (
                      currentEmbeddingModel && (
                        <Disabled
                          disabled={isReindexing}
                          tooltip="请先取消正在进行的重新索引，再切换模型。"
                        >
                          <Tabs
                            value={activeModelTab}
                            onValueChange={setActiveModelTab}
                            variant="underline"
                          >
                            <Card
                              expandable
                              expanded={viewAllModelsOpen}
                              expandableContentHeight="fit"
                              border="solid"
                              borderColor={statusVariant}
                              rounding="lg"
                              padding={viewAllModelsOpen ? "fit" : "sm"}
                              expandedContent={
                                <>
                                  <Tabs.Content value={MODEL_TAB_CLOUD}>
                                    {filteredCloudProviders.length > 0 ? (
                                      <GeneralLayouts.Section
                                        gap={0.5}
                                        padding={0.5}
                                      >
                                        {filteredCloudProviders.map(
                                          (provider) => (
                                            <ProviderGroup
                                              key={provider.providerName}
                                              provider={provider}
                                              currentModelName={
                                                currentEmbeddingModel?.model_name
                                              }
                                              selectedModelName={
                                                stagedModelName ?? undefined
                                              }
                                              isCloud
                                              existingCredentials={configuredProviders?.get(
                                                provider.providerName
                                              )}
                                              existingModel={
                                                currentEmbeddingModel?.provider_type ===
                                                provider.providerName
                                                  ? (currentEmbeddingModelSpec ??
                                                    undefined)
                                                  : undefined
                                              }
                                              onSelectModel={(
                                                name,
                                                customModel
                                              ) => {
                                                void setFieldValue(
                                                  "model_name",
                                                  name
                                                );
                                                void setFieldValue(
                                                  "custom_model",
                                                  customModel ?? null
                                                );
                                                // Bind a just-defined LiteLLM /
                                                // Azure model to its provider so
                                                // submit doesn't misresolve it.
                                                void setFieldValue(
                                                  "custom_model_provider",
                                                  customModel
                                                    ? provider.providerName
                                                    : null
                                                );
                                              }}
                                              onDeselectModel={() => {
                                                void setFieldValue(
                                                  "model_name",
                                                  initialFormValues.model_name
                                                );
                                                void setFieldValue(
                                                  "custom_model",
                                                  null
                                                );
                                                void setFieldValue(
                                                  "custom_model_provider",
                                                  null
                                                );
                                              }}
                                            />
                                          )
                                        )}
                                      </GeneralLayouts.Section>
                                    ) : (
                                      <IllustrationContent
                                        illustration={SvgNoResult}
                                        title="未找到云端模型"
                                        description="请尝试其他搜索词。"
                                      />
                                    )}
                                  </Tabs.Content>

                                  <Tabs.Content value={MODEL_TAB_SELF}>
                                    {filteredSelfHostedProviders.length > 0 ? (
                                      <GeneralLayouts.Section
                                        gap={0.5}
                                        padding={0.5}
                                      >
                                        {filteredSelfHostedProviders.map(
                                          (shProvider) => (
                                            <ProviderGroup
                                              key={shProvider.providerName}
                                              provider={shProvider}
                                              currentModelName={
                                                currentEmbeddingModel?.model_name
                                              }
                                              selectedModelName={
                                                stagedModelName ?? undefined
                                              }
                                              onSelectModel={(name) => {
                                                void setFieldValue(
                                                  "model_name",
                                                  name
                                                );
                                                void setFieldValue(
                                                  "custom_model",
                                                  null
                                                );
                                                void setFieldValue(
                                                  "custom_model_provider",
                                                  null
                                                );
                                              }}
                                              onDeselectModel={() => {
                                                void setFieldValue(
                                                  "model_name",
                                                  initialFormValues.model_name
                                                );
                                                void setFieldValue(
                                                  "custom_model",
                                                  null
                                                );
                                                void setFieldValue(
                                                  "custom_model_provider",
                                                  null
                                                );
                                              }}
                                            />
                                          )
                                        )}

                                        <GeneralLayouts.Section gap={0.25}>
                                          <div className="px-1 pt-1 w-full h-(--height-line-h1-headline)">
                                            <GeneralLayouts.Section
                                              flexDirection="row"
                                              gap={0}
                                            >
                                              <Spacer
                                                orientation="horizontal"
                                                rem={0.675}
                                              />
                                              <div className="flex flex-row justify-between items-center w-full py-1">
                                                <Content
                                                  icon={CUSTOM_PROVIDER.icon}
                                                  title="自定义模型"
                                                  sizePreset="secondary"
                                                />
                                              </div>
                                            </GeneralLayouts.Section>
                                          </div>

                                          <SelectCard
                                            state="filled"
                                            rounding="md"
                                            padding="sm"
                                            onClick={() =>
                                              customModelModal.toggle(true)
                                            }
                                          >
                                            <ContentAction
                                              title="设置自定义嵌入模型。"
                                              sizePreset="secondary"
                                              variant="body"
                                              color="muted"
                                              padding="md"
                                              rightChildren={
                                                <Button
                                                  prominence="tertiary"
                                                  rightIcon={SvgPlusCircle}
                                                  onClick={() =>
                                                    customModelModal.toggle(
                                                      true
                                                    )
                                                  }
                                                >
                                                  添加自定义模型
                                                </Button>
                                              }
                                              center
                                            />
                                          </SelectCard>
                                        </GeneralLayouts.Section>
                                      </GeneralLayouts.Section>
                                    ) : (
                                      <IllustrationContent
                                        illustration={SvgNoResult}
                                        title="未找到自托管模型"
                                        description="请尝试其他搜索词。"
                                      />
                                    )}
                                  </Tabs.Content>
                                </>
                              }
                            >
                              {viewAllModelsOpen ? (
                                <div className="pt-1 px-1">
                                  <div className="pt-2 pb-1 px-2 flex flex-row items-center justify-between">
                                    <InputTypeIn
                                      placeholder="搜索模型..."
                                      variant="internal"
                                      searchIcon
                                      value={query}
                                      onChange={(e) => setQuery(e.target.value)}
                                    />
                                    <div className="flex flex-row">
                                      {isModelStaged && (
                                        <Button
                                          icon={SvgRevert}
                                          prominence="internal"
                                          tooltip="还原嵌入模型选择"
                                          onClick={() => {
                                            void setFieldValue(
                                              "model_name",
                                              initialFormValues.model_name
                                            );
                                            void setFieldValue(
                                              "custom_model",
                                              null
                                            );
                                            void setFieldValue(
                                              "custom_model_provider",
                                              null
                                            );
                                          }}
                                        />
                                      )}
                                      <Button
                                        prominence="internal"
                                        onClick={() =>
                                          setViewAllModelsOpen(false)
                                        }
                                        rightIcon={SvgFold}
                                      >
                                        收起模型
                                      </Button>
                                    </div>
                                  </div>

                                  <div className="px-2">
                                    <Tabs.List>
                                      <Tabs.Trigger value={MODEL_TAB_CLOUD}>
                                        云端
                                      </Tabs.Trigger>
                                      <Tabs.Trigger value={MODEL_TAB_SELF}>
                                        自托管
                                      </Tabs.Trigger>
                                    </Tabs.List>
                                  </div>
                                </div>
                              ) : (
                                <div className="flex flex-row items-start w-full">
                                  <GeneralLayouts.Section
                                    padding={0.5}
                                    gap={0}
                                    alignItems="start"
                                  >
                                    <Content
                                      icon={currentProvider?.icon ?? SvgServer}
                                      title={currentEmbeddingModel.model_name}
                                      description={
                                        findRegistryModel(
                                          currentEmbeddingModel.model_name
                                        )?.description
                                      }
                                      sizePreset="main-ui"
                                      variant="section"
                                    />
                                    <div className="flex flex-row items-center gap-2 pt-2 px-6">
                                      {currentProviderName && (
                                        <EmbeddingProviderInfo
                                          providerName={currentProviderName}
                                        />
                                      )}
                                    </div>
                                  </GeneralLayouts.Section>

                                  <div className="flex flex-col justify-start items-end shrink-0 gap-1 p-2">
                                    <Button
                                      prominence="secondary"
                                      onClick={() => {
                                        const isStagedSelfHosted =
                                          stagedModelName &&
                                          SELF_HOSTED_PROVIDERS.some((p) =>
                                            p.embeddingModels.some(
                                              (m) =>
                                                m.modelName === stagedModelName
                                            )
                                          );
                                        setActiveModelTab(
                                          isStagedSelfHosted
                                            ? MODEL_TAB_SELF
                                            : stagedModelName
                                              ? MODEL_TAB_CLOUD
                                              : currentEmbeddingModel?.provider_type
                                                ? MODEL_TAB_CLOUD
                                                : MODEL_TAB_SELF
                                        );
                                        setViewAllModelsOpen(true);
                                      }}
                                    >
                                      查看全部模型
                                    </Button>
                                    {isCurrentCloudBased && (
                                      <div className="p-1">
                                        <Button
                                          icon={SvgSettings}
                                          prominence="tertiary"
                                          size="md"
                                          onClick={() => editModal.toggle(true)}
                                        />
                                      </div>
                                    )}
                                  </div>
                                </div>
                              )}
                            </Card>
                          </Tabs>
                        </Disabled>
                      )
                    )}
                  </GeneralLayouts.Section>

                  <Divider paddingParallel="fit" paddingPerpendicular="fit" />

                  {/* ── Retrieval Optimization ── */}
                  <GeneralLayouts.Section
                    gap={0.75}
                    height="fit"
                    alignItems="stretch"
                    justifyContent="start"
                  >
                    <Content
                      title="检索优化"
                      description="通过配置文档分块和上下文化方式提升搜索准确性的额外索引功能。这可能增加嵌入成本。"
                      sizePreset="main-content"
                      variant="section"
                    />

                    <CloudDisabled
                      disabled
                      tooltip="多轮索引暂时不可用，未来会开放。"
                    >
                      <Card border="solid" rounding="lg">
                        <InputHorizontal
                          title="多轮索引"
                          description="以不同大小的分块索引文档，以便更好地识别相关来源。"
                          tag={{
                            title: "暂不可用",
                            color: "gray",
                          }}
                          withLabel
                        >
                          <Switch
                            checked={
                              searchSettings?.multipass_indexing ?? false
                            }
                            disabled
                          />
                        </InputHorizontal>
                      </Card>
                    </CloudDisabled>

                    <CloudDisabled
                      disabled={isReindexing || !hasAnyLlm}
                      tooltip={
                        isReindexing
                          ? "请先取消正在进行的重新索引，再修改检索设置。"
                          : !hasAnyLlm
                            ? markdown(
                                "上下文检索已禁用，因为你还没有配置模型。请先设置一个[语言模型](/admin/configuration/language-models)。"
                              )
                            : undefined
                      }
                    >
                      <Card
                        border="solid"
                        borderColor={statusVariant}
                        rounding="lg"
                      >
                        <GeneralLayouts.Section width="full">
                          <InputHorizontal
                            title="上下文检索"
                            description="为每个索引分块添加文档级上下文，以提升混合搜索相关性。这可能显著增加嵌入成本。"
                            withLabel
                          >
                            <SwitchField name="enable_contextual_rag" />
                          </InputHorizontal>

                          <Disabled
                            disabled={!values.enable_contextual_rag}
                            tooltip="上下文检索关闭时无法修改。"
                          >
                            <InputHorizontal
                              title="上下文检索 LLM"
                              description="此模型将用于为分块生成上下文。"
                              disabled={!values.enable_contextual_rag}
                              withLabel
                            >
                              <LlmPicker
                                modelConfigurationId={
                                  values.contextual_rag_model_configuration_id
                                }
                                disabled={!values.enable_contextual_rag}
                                onChange={({ modelConfigurationId }) => {
                                  void setFieldValue(
                                    "contextual_rag_model_configuration_id",
                                    modelConfigurationId
                                  );
                                }}
                              />
                            </InputHorizontal>
                          </Disabled>
                        </GeneralLayouts.Section>
                      </Card>
                    </CloudDisabled>
                  </GeneralLayouts.Section>

                  <Divider paddingParallel="fit" paddingPerpendicular="fit" />

                  {/* ── Image Processing ── */}
                  <GeneralLayouts.Section
                    gap={0.75}
                    height="fit"
                    alignItems="stretch"
                    justifyContent="start"
                  >
                    <Content
                      title="图片处理"
                      description="索引时使用 LLM 分析图片并添加描述。"
                      sizePreset="main-content"
                      variant="section"
                    />

                    <Disabled
                      disabled={!hasAnyVisionLlm}
                      tooltip={
                        !hasAnyVisionLlm
                          ? markdown(
                              "图片处理已禁用，因为你还没有配置支持视觉的模型。请先设置一个支持视觉的[语言模型](/admin/configuration/language-models)。"
                            )
                          : undefined
                      }
                    >
                      <Card border="solid" rounding="lg">
                        <GeneralLayouts.Section width="full">
                          <InputHorizontal
                            title="提取并描述图片"
                            description="从上传文件（PDF、DOCX 等）中提取嵌入图片，并用支持视觉的 LLM 总结图片内容，使纯图片文档也可被搜索和回答。需要支持视觉的默认 LLM。"
                            withLabel
                          >
                            <Switch
                              checked={imageProcessingEnabled}
                              onCheckedChange={(checked) => {
                                void saveSettings({
                                  image_extraction_and_analysis_enabled:
                                    checked,
                                });
                              }}
                            />
                          </InputHorizontal>

                          <Disabled
                            disabled={!imageProcessingEnabled}
                            tooltip="请先启用“提取并描述图片”再配置此项。"
                          >
                            <InputHorizontal
                              title="图片描述 LLM"
                              description="此模型会在索引期间分析图片。只能选择支持视觉的模型。更新仅对后续索引的文档生效，已有图片描述已写入此前的嵌入结果。"
                              disabled={!imageProcessingEnabled}
                              withLabel
                            >
                              <LlmPicker
                                modelName={defaultVision?.modelName ?? null}
                                providerName={
                                  defaultVision?.providerName ?? null
                                }
                                disabled={!imageProcessingEnabled}
                                onChange={handleCaptioningModelChange}
                                requiresImageInput
                              />
                            </InputHorizontal>
                          </Disabled>

                          <Disabled
                            disabled={!imageProcessingEnabled}
                            tooltip="请先启用“提取并描述图片”再配置此项。"
                          >
                            <InputHorizontal
                              title="图片分析最大大小"
                              suffix="(MB)"
                              description="超过此大小的图片会被跳过，以限制资源使用。"
                              disabled={!imageProcessingEnabled}
                              withLabel
                            >
                              <InputSelect
                                value={String(
                                  settings.settings
                                    .image_analysis_max_size_mb ?? 20
                                )}
                                onValueChange={(value) => {
                                  void saveSettings({
                                    image_analysis_max_size_mb: parseInt(
                                      value,
                                      10
                                    ),
                                  });
                                }}
                                disabled={!imageProcessingEnabled}
                              >
                                <InputSelect.Trigger />
                                <InputSelect.Content>
                                  {MAX_IMAGE_SIZE_OPTIONS.map((size) => (
                                    <InputSelect.Item key={size} value={size}>
                                      {size}
                                    </InputSelect.Item>
                                  ))}
                                </InputSelect.Content>
                              </InputSelect>
                            </InputHorizontal>
                          </Disabled>
                        </GeneralLayouts.Section>
                      </Card>
                    </Disabled>
                  </GeneralLayouts.Section>
                </>
              );
            }}
          </Formik>
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    </>
  );
}
