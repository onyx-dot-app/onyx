"use client";

import { useTranslations } from "next-intl";
import {
  Button,
  InputPasswordTypeIn,
  InputSingleSelect,
  InputTypeIn,
} from "@opal/components";
import { SvgPlus, SvgTrash } from "@opal/icons";
import { InputVertical, Section } from "@opal/layouts";
import type {
  AuthMethod,
  AuthMode,
  IntegrationShape,
} from "@/lib/integrations/types";
import {
  PROVIDER_MODES,
  signInErrors,
  type HeaderDraft,
  type SignInDraft,
} from "@/sections/integrations/signIn";

const AUTH_MODES: readonly AuthMode[] = ["none", "shared", "individual"];

interface IntegrationSignInFieldsProps {
  draft: SignInDraft;
  onChange: (draft: SignInDraft) => void;
  methods: readonly AuthMethod[];
  shape: IntegrationShape;
  showErrors: boolean;
  disabled: boolean;
}

export default function IntegrationSignInFields({
  draft,
  onChange,
  methods,
  shape,
  showErrors,
  disabled,
}: IntegrationSignInFieldsProps) {
  const providerModes = PROVIDER_MODES[shape];
  const authModes: readonly AuthMode[] = methods.length ? AUTH_MODES : ["none"];
  const t = useTranslations("admin.integrations.signIn");
  const errors = showErrors ? signInErrors(draft) : [];
  const variant = disabled ? "disabled" : "primary";

  function update(patch: Partial<SignInDraft>) {
    onChange({ ...draft, ...patch });
  }

  function updateHeader(index: number, patch: Partial<HeaderDraft>) {
    update({
      headers: draft.headers.map((header, other) =>
        other === index ? { ...header, ...patch } : header
      ),
    });
  }

  function errorFor(
    field: (typeof errors)[number],
    message: string
  ): string | undefined {
    return errors.includes(field) ? message : undefined;
  }

  const methodLabels: Record<AuthMethod, string> = {
    oauth2: t("method.oauth2"),
    api_key: t("method.apiKey"),
    onyx_login: t("method.onyxLogin"),
    managed: t("method.managed"),
  };

  return (
    <Section gap={4} alignItems="stretch" height="auto">
      <InputVertical
        title={t("mode.title")}
        description={t("mode.description")}
      >
        <InputSingleSelect
          placeholder={t("mode.title")}
          value={draft.authMode}
          disabled={disabled}
          options={authModes.map((mode) => ({
            value: mode,
            title: t(`mode.${mode}`),
          }))}
          onValueChange={(value) => {
            const mode = authModes.find((option) => option === value);
            if (!mode) return;
            update({
              authMode: mode,
              authMethod:
                mode === "none" ? null : (draft.authMethod ?? methods[0]),
            });
          }}
        />
      </InputVertical>
      {draft.authMode !== "none" && methods.length > 0 && (
        <InputVertical title={t("method.title")}>
          <InputSingleSelect
            placeholder={t("method.title")}
            value={draft.authMethod ?? ""}
            disabled={disabled}
            options={methods.map((method) => ({
              value: method,
              title: methodLabels[method],
            }))}
            onValueChange={(value) => {
              const method = methods.find((option) => option === value);
              if (method) update({ authMethod: method });
            }}
          />
        </InputVertical>
      )}
      {draft.authMode !== "none" && draft.authMethod === "api_key" && (
        <>
          {draft.headers.map((header, index) => {
            const suffix = index === 0 ? "" : ` ${index + 1}`;
            const last = index === draft.headers.length - 1;
            const name = header.name.trim().toLowerCase();
            const repeated = draft.headers
              .slice(0, index)
              .some((other) => other.name.trim().toLowerCase() === name);
            return (
              <Section key={index} gap={2} alignItems="stretch" height="auto">
                <InputVertical
                  title={t("header.name.title")}
                  error={
                    !name
                      ? errorFor("headerName", t("header.name.error"))
                      : repeated
                        ? errorFor(
                            "headerDuplicate",
                            t("header.name.duplicate")
                          )
                        : undefined
                  }
                >
                  <Section
                    flexDirection="row"
                    gap={1}
                    alignItems="center"
                    height="auto"
                  >
                    <InputTypeIn
                      aria-label={t("header.name.title") + suffix}
                      placeholder={t("header.name.placeholder")}
                      value={header.name}
                      variant={variant}
                      onChange={(event) =>
                        updateHeader(index, { name: event.target.value })
                      }
                    />
                    {draft.headers.length > 1 && (
                      <Button
                        size="sm"
                        prominence="tertiary"
                        icon={SvgTrash}
                        disabled={disabled}
                        aria-label={t("header.remove", {
                          name: header.name || String(index + 1),
                        })}
                        onClick={() =>
                          update({
                            headers: draft.headers.filter(
                              (_, other) => other !== index
                            ),
                          })
                        }
                      />
                    )}
                  </Section>
                </InputVertical>
                <InputVertical
                  title={t("header.value.title")}
                  description={
                    last
                      ? t("header.value.description", { example: "{api_key}" })
                      : undefined
                  }
                  error={
                    last
                      ? errorFor(
                          "headerValue",
                          t("header.value.error", { example: "{api_key}" })
                        )
                      : undefined
                  }
                >
                  <InputTypeIn
                    aria-label={t("header.value.title") + suffix}
                    placeholder={t("header.value.placeholder", {
                      example: "Bearer {api_key}",
                    })}
                    value={header.value}
                    variant={variant}
                    onChange={(event) =>
                      updateHeader(index, { value: event.target.value })
                    }
                  />
                </InputVertical>
              </Section>
            );
          })}
          <Section alignItems="start" height="auto">
            <Button
              size="sm"
              prominence="secondary"
              icon={SvgPlus}
              disabled={disabled}
              onClick={() =>
                update({ headers: [...draft.headers, { name: "", value: "" }] })
              }
            >
              {t("header.add")}
            </Button>
          </Section>
        </>
      )}
      {draft.authMode !== "none" && draft.authMethod === "oauth2" && (
        <>
          {providerModes.length > 1 && (
            <InputVertical title={t("oauth.providerMode.title")}>
              <InputSingleSelect
                placeholder={t("oauth.providerMode.title")}
                value={draft.providerMode}
                disabled={disabled}
                options={providerModes.map((mode) => ({
                  value: mode,
                  title: t(`oauth.providerMode.${mode}`),
                }))}
                onValueChange={(value) => {
                  const mode = providerModes.find((option) => option === value);
                  if (mode) update({ providerMode: mode });
                }}
              />
            </InputVertical>
          )}
          {draft.providerMode === "manual" && (
            <>
              <InputVertical
                title={t("oauth.authorizationUrl")}
                error={errorFor("authorizationUrl", t("oauth.urlError"))}
              >
                <InputTypeIn
                  aria-label={t("oauth.authorizationUrl")}
                  placeholder={t("oauth.urlPlaceholder")}
                  value={draft.authorizationUrl}
                  variant={variant}
                  onChange={(event) =>
                    update({ authorizationUrl: event.target.value })
                  }
                />
              </InputVertical>
              <InputVertical
                title={t("oauth.tokenUrl")}
                error={errorFor("tokenUrl", t("oauth.urlError"))}
              >
                <InputTypeIn
                  aria-label={t("oauth.tokenUrl")}
                  placeholder={t("oauth.urlPlaceholder")}
                  value={draft.tokenUrl}
                  variant={variant}
                  onChange={(event) => update({ tokenUrl: event.target.value })}
                />
              </InputVertical>
              <InputVertical
                title={t("oauth.clientId")}
                error={errorFor("clientId", t("oauth.clientIdError"))}
              >
                <InputTypeIn
                  aria-label={t("oauth.clientId")}
                  placeholder={t("oauth.clientIdPlaceholder")}
                  value={draft.clientId}
                  variant={variant}
                  onChange={(event) => update({ clientId: event.target.value })}
                />
              </InputVertical>
              <InputVertical title={t("oauth.clientSecret")}>
                <InputPasswordTypeIn
                  aria-label={t("oauth.clientSecret")}
                  placeholder={
                    draft.hasClientSecret
                      ? t("oauth.clientSecretSaved")
                      : t("oauth.clientSecretPlaceholder")
                  }
                  value={draft.clientSecret}
                  disabled={disabled}
                  onChange={(event) =>
                    update({ clientSecret: event.target.value })
                  }
                />
              </InputVertical>
            </>
          )}
          <InputVertical
            title={t("oauth.scopes.title")}
            description={t("oauth.scopes.description")}
          >
            <InputTypeIn
              aria-label={t("oauth.scopes.title")}
              placeholder={t("oauth.scopes.placeholder")}
              value={draft.scopes}
              variant={variant}
              onChange={(event) => update({ scopes: event.target.value })}
            />
          </InputVertical>
        </>
      )}
    </Section>
  );
}
