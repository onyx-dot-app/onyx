"use client";
import { useTranslations } from "next-intl";
import { useFormikContext } from "formik";
import type { MCPAuthFormValues } from "@/sections/actions/modals/types";
import { FormField } from "@/refresh-components/form/FormField";
import { InputSwitchField } from "@opal/form";
import { Content, InputHorizontal, Section } from "@opal/layouts";
import { useEffect, useRef, useState } from "react";
import {
  Button,
  CopyButton,
  InputTypeIn,
  InputPasswordTypeIn,
  InputSingleSelect,
  MessageCard,
  SelectCard,
  Text,
} from "@opal/components";
import { MCPOAuthProviderMode } from "@/lib/mcp/types";
import type { MCPOAuthDiscovery } from "@/lib/mcp/types";
import { markdown } from "@opal/utils";
import { useSettings } from "@/lib/settings/hooks";
import { SvgCircle, SvgCheckCircle } from "@opal/icons";
interface MCPOAuthFieldsProps extends OAuthDiscoveryStatusProps {
  redirectUri: string;
  onSetupChosen: () => void;
  onSettingsChange: () => void;
  disabled?: boolean;
}
export function MCPOAuthFields({
  hasChosenSetup,
  onSetupChosen,
  discovery: oauthDiscovery,
  checking,
  failed,
  onRetry,
  redirectUri,
  onSettingsChange,
  disabled = false,
}: MCPOAuthFieldsProps) {
  const t = useTranslations("actions");
  const recommendedCopy = useTranslations("craft.llmPopover.recommended");
  const recommendedMode =
    !checking && !failed && oauthDiscovery?.status === "metadata_found"
      ? oauthDiscovery.supports_automatic_registration === true
        ? "automatic"
        : oauthDiscovery.supports_automatic_registration === false
          ? "own_client"
          : undefined
      : undefined;
  const { appName } = useSettings();
  const {
    values,
    initialValues,
    setValues,
    setFieldValue,
    errors,
    touched,
    handleChange,
  } = useFormikContext<MCPAuthFormValues>();
  // The server's masked secret, captured before a save can reset the form to
  // the typed plaintext.
  const [storedClientSecret] = useState(
    () => initialValues.oauth_client_secret
  );
  const automaticRef = useRef<HTMLDivElement>(null);
  const ownClientRef = useRef<HTMLDivElement>(null);
  function chooseSetup(value: MCPAuthFormValues["oauth_setup_mode"]) {
    if (disabled) return;
    onSetupChosen();
    if (value === values.oauth_setup_mode) return;
    onSettingsChange();
    if (value === "automatic") {
      setValues({
        ...values,
        oauth_setup_mode: value,
        oauth_client_id: "",
        oauth_client_secret: "",
        oauth_provider_mode: MCPOAuthProviderMode.AUTO_DISCOVERY,
        oauth_authorization_endpoint: "",
        oauth_token_endpoint: "",
        oauth_scopes_override: "",
        oauth_additional_auth_params: "",
      });
    } else {
      setFieldValue("oauth_setup_mode", value);
    }
  }
  return (
    <Section alignItems="stretch" height="auto" gap={4}>
      <div
        role="radiogroup"
        aria-label={t("mcpAuthModal.oauthSetup.label")}
        className="flex flex-col gap-2"
      >
        {(["automatic", "own_client"] as const).map((mode) => {
          const copyKey = mode === "automatic" ? "automatic" : "ownClient";
          return (
            <SelectCard
              key={mode}
              ref={mode === "automatic" ? automaticRef : ownClientRef}
              role="radio"
              aria-label={t(`mcpAuthModal.oauthSetup.${copyKey}.label`)}
              aria-checked={values.oauth_setup_mode === mode}
              tabIndex={values.oauth_setup_mode === mode ? 0 : -1}
              state={values.oauth_setup_mode === mode ? "selected" : "empty"}
              disabled={disabled}
              padding={3}
              rounding={2}
              onClick={() => chooseSetup(mode)}
              onKeyDown={(event) => {
                if (disabled) return;
                if (
                  ![
                    "ArrowDown",
                    "ArrowUp",
                    "ArrowLeft",
                    "ArrowRight",
                    "Home",
                    "End",
                  ].includes(event.key)
                )
                  return;
                event.preventDefault();
                const next =
                  event.key === "Home"
                    ? "automatic"
                    : event.key === "End"
                      ? "own_client"
                      : mode === "automatic"
                        ? "own_client"
                        : "automatic";
                chooseSetup(next);
                (next === "automatic"
                  ? automaticRef
                  : ownClientRef
                ).current?.focus();
              }}
            >
              <Content
                icon={
                  values.oauth_setup_mode === mode ? SvgCheckCircle : SvgCircle
                }
                sizePreset="main-ui"
                variant="section"
                color="interactive"
                title={t(`mcpAuthModal.oauthSetup.${copyKey}.label`)}
                description={t(
                  `mcpAuthModal.oauthSetup.${copyKey}.description`,
                  { appName }
                )}
                tag={
                  recommendedMode === mode
                    ? { title: recommendedCopy("label"), color: "green" }
                    : undefined
                }
              />
            </SelectCard>
          );
        })}
      </div>
      <Section alignItems="stretch" height="auto" gap={4}>
        <OAuthDiscoveryStatus
          hasChosenSetup={hasChosenSetup}
          discovery={oauthDiscovery}
          checking={checking}
          failed={failed}
          onRetry={onRetry}
        />
        {values.oauth_setup_mode === "automatic" && (
          <InputHorizontal
            withLabel="oauth_cimd_enabled"
            title={t("mcpAuthModal.cimd.label")}
            description={t("mcpAuthModal.cimd.description", { appName })}
          >
            <InputSwitchField
              name="oauth_cimd_enabled"
              disabled={disabled}
              onCheckedChange={onSettingsChange}
            />
          </InputHorizontal>
        )}
        {values.oauth_setup_mode === "own_client" && (
          <>
            <Section alignItems="stretch" height="auto" gap={4}>
              <FormField
                name="oauth_client_id"
                state={
                  errors.oauth_client_id && touched.oauth_client_id
                    ? "error"
                    : touched.oauth_client_id
                      ? "success"
                      : "idle"
                }
              >
                <FormField.Label>
                  {t("mcpAuthModal.clientId.label")}
                </FormField.Label>
                <FormField.Control asChild>
                  <InputTypeIn
                    name="oauth_client_id"
                    value={values.oauth_client_id}
                    onChange={handleChange}
                    placeholder=" "
                  />
                </FormField.Control>
                <FormField.Message
                  messages={{
                    error: errors.oauth_client_id,
                  }}
                />
              </FormField>
              <FormField
                name="oauth_client_secret"
                state={
                  errors.oauth_client_secret && touched.oauth_client_secret
                    ? "error"
                    : touched.oauth_client_secret
                      ? "success"
                      : "idle"
                }
              >
                <FormField.Label optional>
                  {t("mcpAuthModal.clientSecret.label")}
                </FormField.Label>
                <FormField.Control asChild>
                  <InputPasswordTypeIn
                    name="oauth_client_secret"
                    value={values.oauth_client_secret}
                    onChange={handleChange}
                    existingValue={storedClientSecret}
                    placeholder=" "
                  />
                </FormField.Control>
                <FormField.Message
                  messages={{
                    error: errors.oauth_client_secret,
                  }}
                />
              </FormField>

              <div className="flex flex-col gap-2">
                <Text as="p" font="secondary-body" color="text-03">
                  {t("mcpAuthModal.oauthInfo.manualRegistration", {
                    appName,
                  })}
                </Text>
                <div className="flex items-center gap-1 w-full">
                  <Text
                    as="p"
                    font="secondary-body"
                    color="text-03"
                    wordWrap="whitespace-nowrap"
                  >
                    {markdown(t("mcpAuthModal.redirectUri.label"))}
                  </Text>
                  <Text
                    as="p"
                    font="secondary-mono"
                    color="text-04"
                    maxLines={1}
                  >
                    {redirectUri}
                  </Text>
                  <CopyButton
                    getCopyText={() => redirectUri}
                    tooltip={t("mcpAuthModal.redirectUri.copyTooltip")}
                    prominence="tertiary"
                    size="sm"
                  />
                </div>
              </div>
            </Section>
            <Section alignItems="stretch" height="auto">
              <FormField
                name="oauth_provider_mode"
                state={
                  errors.oauth_provider_mode && touched.oauth_provider_mode
                    ? "error"
                    : touched.oauth_provider_mode
                      ? "success"
                      : "idle"
                }
              >
                <FormField.Label>
                  {t("mcpAuthModal.providerMode.label")}
                </FormField.Label>
                <FormField.Control asChild>
                  <InputSingleSelect
                    value={values.oauth_provider_mode}
                    onValueChange={(value) => {
                      onSettingsChange();
                      setFieldValue("oauth_provider_mode", value);
                    }}
                    defaultOption={MCPOAuthProviderMode.AUTO_DISCOVERY}
                    placeholder={t("mcpAuthModal.providerMode.placeholder")}
                    options={[
                      {
                        value: MCPOAuthProviderMode.AUTO_DISCOVERY,
                        title: t(
                          "mcpAuthModal.providerMode.autoDiscovery.label"
                        ),
                        description: t(
                          "mcpAuthModal.providerMode.autoDiscovery.description"
                        ),
                      },
                      {
                        value: MCPOAuthProviderMode.KNOWN_PROVIDER,
                        title: t(
                          "mcpAuthModal.providerMode.knownProvider.label"
                        ),
                        description: t(
                          "mcpAuthModal.providerMode.knownProvider.description"
                        ),
                      },
                    ]}
                  />
                </FormField.Control>
              </FormField>

              {values.oauth_provider_mode ===
                MCPOAuthProviderMode.KNOWN_PROVIDER && (
                <>
                  <FormField
                    name="oauth_authorization_endpoint"
                    state={
                      errors.oauth_authorization_endpoint &&
                      touched.oauth_authorization_endpoint
                        ? "error"
                        : touched.oauth_authorization_endpoint
                          ? "success"
                          : "idle"
                    }
                  >
                    <FormField.Label>
                      {t("mcpAuthModal.authorizationEndpoint.label")}
                    </FormField.Label>
                    <FormField.Control asChild>
                      <InputTypeIn
                        name="oauth_authorization_endpoint"
                        value={values.oauth_authorization_endpoint}
                        onChange={handleChange}
                        placeholder="https://example.com/oauth/authorize"
                      />
                    </FormField.Control>
                    <FormField.Message
                      messages={{
                        error: errors.oauth_authorization_endpoint,
                      }}
                    />
                  </FormField>

                  <FormField
                    name="oauth_token_endpoint"
                    state={
                      errors.oauth_token_endpoint &&
                      touched.oauth_token_endpoint
                        ? "error"
                        : touched.oauth_token_endpoint
                          ? "success"
                          : "idle"
                    }
                  >
                    <FormField.Label>
                      {t("mcpAuthModal.tokenEndpoint.label")}
                    </FormField.Label>
                    <FormField.Control asChild>
                      <InputTypeIn
                        name="oauth_token_endpoint"
                        value={values.oauth_token_endpoint}
                        onChange={handleChange}
                        placeholder="https://example.com/oauth/token"
                      />
                    </FormField.Control>
                    <FormField.Message
                      messages={{
                        error: errors.oauth_token_endpoint,
                      }}
                    />
                  </FormField>

                  <FormField name="oauth_scopes_override">
                    <FormField.Label optional>
                      {t("mcpAuthModal.scopesOverride.label")}
                    </FormField.Label>
                    <FormField.Control asChild>
                      <InputTypeIn
                        name="oauth_scopes_override"
                        value={values.oauth_scopes_override}
                        onChange={handleChange}
                        placeholder={t("placeholders.oauthScope")}
                      />
                    </FormField.Control>
                  </FormField>

                  <FormField
                    name="oauth_additional_auth_params"
                    state={
                      errors.oauth_additional_auth_params ? "error" : "idle"
                    }
                  >
                    <FormField.Label optional>
                      {t("mcpAuthModal.additionalAuthParams.label")}
                    </FormField.Label>
                    <FormField.Control asChild>
                      <InputTypeIn
                        name="oauth_additional_auth_params"
                        value={values.oauth_additional_auth_params}
                        onChange={handleChange}
                        placeholder='{"access_type":"offline","prompt":"consent"}'
                      />
                    </FormField.Control>
                    <FormField.Message
                      messages={{ error: errors.oauth_additional_auth_params }}
                    />
                  </FormField>
                </>
              )}
            </Section>
          </>
        )}
      </Section>
    </Section>
  );
}
interface OAuthDiscoveryStatusProps {
  hasChosenSetup: boolean;
  discovery: MCPOAuthDiscovery | undefined;
  checking: boolean;
  failed: boolean;
  onRetry: () => void;
}

function OAuthDiscoveryStatus({
  hasChosenSetup,
  discovery,
  checking,
  failed,
  onRetry,
}: OAuthDiscoveryStatusProps) {
  const t = useTranslations("actions.mcpAuthModal.discovery");
  const { values, setFieldValue, setValues, dirty, resetForm } =
    useFormikContext<MCPAuthFormValues>();
  const requiresClient = discovery?.supports_automatic_registration === false;
  const hasAppliedRecommendation = useRef(false);
  useEffect(() => {
    if (
      checking ||
      failed ||
      hasChosenSetup ||
      !requiresClient ||
      hasAppliedRecommendation.current
    )
      return;
    hasAppliedRecommendation.current = true;
    if (values.oauth_setup_mode === "automatic") {
      if (dirty) {
        void setFieldValue("oauth_setup_mode", "own_client");
      } else {
        resetForm({ values: { ...values, oauth_setup_mode: "own_client" } });
      }
    }
  }, [
    checking,
    failed,
    hasChosenSetup,
    requiresClient,
    values,
    dirty,
    resetForm,
    setFieldValue,
  ]);

  if (
    (!checking && !failed && !discovery) ||
    values.oauth_setup_mode === "own_client" ||
    values.oauth_provider_mode === MCPOAuthProviderMode.KNOWN_PROVIDER
  )
    return null;
  const missing = discovery?.status === "metadata_missing";
  const unreachable = failed || discovery?.status === "unreachable";
  if (!checking && !requiresClient && !missing && !unreachable) return null;
  const title = checking
    ? t("checking")
    : requiresClient
      ? t("requiresClientTitle")
      : missing
        ? t("missingTitle")
        : unreachable
          ? t("unreachableTitle")
          : t("supported");
  const description = checking
    ? undefined
    : requiresClient
      ? t("requiresClient")
      : missing
        ? t("missing")
        : unreachable
          ? t("unreachable")
          : undefined;
  return (
    <div role="status">
      <MessageCard
        variant={
          checking
            ? "pending"
            : missing || unreachable || requiresClient
              ? "warning"
              : "success"
        }
        outerPadding={1}
        innerPadding={1}
        title={title}
        description={description}
      />
      {!checking && (missing || unreachable) && (
        <div className="flex flex-wrap justify-end gap-2 pt-2">
          <Button type="button" prominence="secondary" onClick={onRetry}>
            {t("retry")}
          </Button>
          {missing && (
            <Button
              type="button"
              prominence="secondary"
              onClick={() => {
                void setValues({
                  ...values,
                  oauth_setup_mode: "own_client",
                  oauth_provider_mode: MCPOAuthProviderMode.KNOWN_PROVIDER,
                });
              }}
            >
              {t("manual")}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
