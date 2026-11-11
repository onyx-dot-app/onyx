"use client";

import { useMemo, useState } from "react";
import { Form, Formik, useFormikContext } from "formik";
import { useTranslations } from "next-intl";
import * as Yup from "yup";
import { markdown } from "@opal/utils";
import { Button, Card, InputCheckbox, Modal, Text } from "@opal/components";
import { InputDivider, InputHorizontal, Section, toast } from "@opal/layouts";
import { useWellKnownLLMProvider } from "@/lib/languageModels/hooks";
import {
  fetchOpenRouterModels,
  fetchTypeSafeModels,
  fetchVercelAIGatewayModels,
} from "@/lib/languageModels/svc";
import { getProvider } from "@/lib/languageModels/utils";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import type { ErrorResponseBody } from "@/lib/fetcher";
import type {
  LLMProviderView,
  ModelConfiguration,
} from "@/lib/languageModels/types";
import {
  APIBaseField,
  APIKeyField,
  DisplayNameField,
  RefetchButton,
} from "@/sections/modals/languageModels/shared";

interface DecisionProviderValues {
  name: string;
  api_key: string;
  api_base: string;
  selected_model_names: string[];
}

interface DecisionProviderModalProps {
  providerName: string;
  existingLlmProvider?: LLMProviderView;
  onOpenChange?: (open: boolean) => void;
  onSuccess?: () => void | Promise<void>;
}

interface DecisionProviderConnection {
  id?: number;
  provider: string;
  api_key?: string;
  api_key_changed: boolean;
  api_base?: string;
}

type DecisionProviderRequest = DecisionProviderConnection &
  ({ name: string | null; selected_model_names: string[] } | { model: string });

async function requestDecisionProvider(
  path: string,
  method: string,
  body: DecisionProviderRequest
) {
  const response = await fetch(`/api/admin/llm/decision-provider${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const error: ErrorResponseBody = await response.json().catch(() => ({}));
    throw new Error(error.detail || error.message || response.statusText);
  }
}

function DecisionProviderFields({
  providerName,
  existingLlmProvider,
  models,
  setFetchedModels,
  onClose,
}: DecisionProviderModalProps & {
  models: ModelConfiguration[];
  setFetchedModels: (models: ModelConfiguration[]) => void;
  onClose: () => void;
}) {
  const t = useTranslations("admin.languageModels.modals");
  const tDecision = useTranslations("admin.decisionModels");
  const { values, setFieldValue, isSubmitting, dirty, isValid } =
    useFormikContext<DecisionProviderValues>();
  const { companyName, productName, icon } = getProvider(providerName);
  const selectedNames = new Set(values.selected_model_names);
  const allSelected =
    models.length > 0 && models.every((model) => selectedNames.has(model.name));

  async function refreshModels(signal: AbortSignal) {
    const params = {
      api_key:
        existingLlmProvider && values.api_key === existingLlmProvider.api_key
          ? undefined
          : values.api_key,
      provider_id: existingLlmProvider?.id,
      signal,
    };
    if (providerName === "typesafe") {
      setFetchedModels(await fetchTypeSafeModels(params));
    } else {
      const fetchModels =
        providerName === "vercel_ai_gateway"
          ? fetchVercelAIGatewayModels
          : fetchOpenRouterModels;
      const result = await fetchModels({
        ...params,
        api_key: values.api_key,
        api_base: values.api_base,
      });
      if (result.error) throw new Error(result.error);
      setFetchedModels(result.models);
    }
  }

  return (
    <Modal open onOpenChange={onClose}>
      <Modal.Content width="lg" height="lg">
        <Form className="h-full min-h-0 flex flex-col">
          <Modal.Header
            icon={icon}
            title={
              existingLlmProvider
                ? markdown(
                    t("setup.title.configure", {
                      provider: existingLlmProvider.name ?? productName,
                    })
                  )
                : t("setup.title.create", { product: productName })
            }
            description={tDecision("providers.description")}
            onClose={onClose}
          />
          <Modal.Body padding={2} gap={0}>
            {(providerName === "openrouter" ||
              providerName === "vercel_ai_gateway") && <APIBaseField />}
            <APIKeyField providerName={companyName} />
            <InputDivider />
            <DisplayNameField />
            <InputDivider />
            <Card color="background-tint-00" border="none" padding={2}>
              <Section gap={2} alignItems="stretch">
                <InputHorizontal
                  title={t("models.field.title")}
                  description={t("models.field.description")}
                >
                  <Section flexDirection="row" gap={0} width="fit">
                    <Button
                      prominence="tertiary"
                      disabled={!models.length || isSubmitting}
                      onClick={() =>
                        setFieldValue(
                          "selected_model_names",
                          allSelected ? [] : models.map((model) => model.name)
                        )
                      }
                    >
                      {t(
                        allSelected
                          ? "models.deselectAllButton.label"
                          : "models.selectAllButton.label"
                      )}
                    </Button>
                    {(providerName === "typesafe" ||
                      providerName === "openrouter" ||
                      providerName === "vercel_ai_gateway") &&
                      (values.api_key || existingLlmProvider) && (
                        <RefetchButton onRefetch={refreshModels} />
                      )}
                  </Section>
                </InputHorizontal>
                {models.some((model) => model.supports_chat !== false) && (
                  <Button
                    href={ADMIN_ROUTES.LLM_MODELS.path}
                    prominence="tertiary"
                  >
                    {tDecision("sharedModelSettings")}
                  </Button>
                )}
                {models.length === 0 && (
                  <Text font="secondary-body" color="text-03">
                    {t("models.empty.title")}
                  </Text>
                )}
                {models.map((model) => (
                  <InputHorizontal
                    key={model.name}
                    title={model.effectiveDisplayName || model.name}
                    withLabel
                  >
                    <InputCheckbox
                      aria-label={model.effectiveDisplayName || model.name}
                      checked={selectedNames.has(model.name)}
                      disabled={isSubmitting}
                      onCheckedChange={(checked) =>
                        setFieldValue(
                          "selected_model_names",
                          checked
                            ? [...values.selected_model_names, model.name]
                            : values.selected_model_names.filter(
                                (name) => name !== model.name
                              )
                        )
                      }
                    />
                  </InputHorizontal>
                ))}
              </Section>
            </Card>
          </Modal.Body>
          <Modal.Footer>
            <Button prominence="secondary" onClick={onClose}>
              {t("setup.cancelButton.label")}
            </Button>
            <Button type="submit" disabled={isSubmitting || !dirty || !isValid}>
              {t(
                existingLlmProvider
                  ? "setup.updateButton.label"
                  : "setup.connectButton.label"
              )}
            </Button>
          </Modal.Footer>
        </Form>
      </Modal.Content>
    </Modal>
  );
}

export default function DecisionProviderModal(
  props: DecisionProviderModalProps
) {
  const { providerName, existingLlmProvider, onOpenChange, onSuccess } = props;
  const t = useTranslations("admin.languageModels.modals");
  const { wellKnownLLMProvider } = useWellKnownLLMProvider(providerName);
  const [fetchedModels, setFetchedModels] = useState<ModelConfiguration[]>([]);
  const models = useMemo(() => {
    const byName = new Map<string, ModelConfiguration>();
    for (const model of [
      ...(existingLlmProvider?.model_configurations ?? []),
      ...(wellKnownLLMProvider?.known_models ?? []),
      ...fetchedModels,
    ]) {
      if (model.supports_decisions) byName.set(model.name, model);
    }
    return [...byName.values()];
  }, [existingLlmProvider, wellKnownLLMProvider, fetchedModels]);
  const initialValues: DecisionProviderValues = {
    name: existingLlmProvider?.name ?? "",
    api_key: existingLlmProvider?.api_key ?? "",
    api_base:
      existingLlmProvider?.api_base ??
      (providerName === "vercel_ai_gateway"
        ? "https://ai-gateway.vercel.sh/v1"
        : providerName === "openrouter"
          ? "https://openrouter.ai/api/v1"
          : ""),
    selected_model_names:
      existingLlmProvider?.model_configurations
        .filter((model) => model.supports_decisions)
        .map((model) => model.name) ?? [],
  };
  const onClose = () => onOpenChange?.(false);

  return (
    <Formik
      initialValues={initialValues}
      validationSchema={Yup.object({
        api_key: Yup.string().required(t("validation.apiKeyRequired")),
        ...(!existingLlmProvider && {
          selected_model_names: Yup.array().min(
            1,
            t("validation.modelNameRequired")
          ),
        }),
        ...((providerName === "openrouter" ||
          providerName === "vercel_ai_gateway") && {
          api_base: Yup.string().required(t("validation.apiBaseRequired")),
        }),
      })}
      validateOnMount
      onSubmit={async (values) => {
        const connection = {
          id: existingLlmProvider?.id,
          provider: providerName,
          api_key:
            values.api_key !== initialValues.api_key || !existingLlmProvider
              ? values.api_key
              : undefined,
          api_key_changed:
            !existingLlmProvider || values.api_key !== initialValues.api_key,
          api_base: values.api_base || undefined,
        };
        try {
          if (
            !existingLlmProvider ||
            connection.api_key_changed ||
            values.api_base !== initialValues.api_base
          ) {
            const testModel = values.selected_model_names[0] ?? models[0]?.name;
            if (testModel)
              await requestDecisionProvider("/test", "POST", {
                ...connection,
                model: testModel,
              });
          }
          await requestDecisionProvider("", "PUT", {
            ...connection,
            name: values.name || null,
            selected_model_names: values.selected_model_names,
          });
          await onSuccess?.();
          onClose();
        } catch (error) {
          toast.error(
            error instanceof Error
              ? error.message
              : t("toasts.testProviderFailed")
          );
        }
      }}
    >
      <DecisionProviderFields
        {...props}
        models={models}
        setFetchedModels={setFetchedModels}
        onClose={onClose}
      />
    </Formik>
  );
}
