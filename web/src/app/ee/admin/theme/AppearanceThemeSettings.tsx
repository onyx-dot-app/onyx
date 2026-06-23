"use client";

import { FormField } from "@/refresh-components/form/FormField";
import {
  Button,
  Divider,
  InputTypeIn,
  Switch,
  Tabs,
  Tag,
} from "@opal/components";
import Preview from "@/app/ee/admin/theme/Preview";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";
import CharacterCount from "@/refresh-components/CharacterCount";
import InputImage from "@/refresh-components/inputs/InputImage";
import { Disabled } from "@opal/core";
import { useFormikContext } from "formik";
import { useTranslation } from "react-i18next";
import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import type { PreviewHighlightTarget } from "./Preview";
import { SvgEdit } from "@opal/icons";
import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { Tier } from "@/lib/settings/types";
import { planTagProps } from "@/lib/tier-badge";

interface AppearanceThemeSettingsProps {
  selectedLogo: File | null;
  setSelectedLogo: (file: File | null) => void;
  logoVersion: number;
  charLimits: {
    application_name: number;
    custom_greeting_message: number;
    custom_header_content: number;
    custom_lower_disclaimer_content: number;
    custom_popup_header: number;
    custom_popup_content: number;
    consent_screen_prompt: number;
  };
}

export interface AppearanceThemeSettingsRef {
  focusFirstError: (errors: Record<string, any>) => void;
}

export const AppearanceThemeSettings = forwardRef<
  AppearanceThemeSettingsRef,
  AppearanceThemeSettingsProps
>(function AppearanceThemeSettings(
  { selectedLogo, setSelectedLogo, logoVersion, charLimits },
  ref
) {
  const { t } = useTranslation();
  const { values, errors, setFieldValue } = useFormikContext<any>();
  const enterpriseTier = useTierAtLeast(Tier.ENTERPRISE);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const applicationNameInputRef = useRef<HTMLInputElement>(null);
  const greetingMessageInputRef = useRef<HTMLInputElement>(null);
  const headerContentInputRef = useRef<HTMLInputElement>(null);
  const lowerDisclaimerInputRef = useRef<HTMLTextAreaElement>(null);
  const noticeHeaderInputRef = useRef<HTMLInputElement>(null);
  const noticeContentInputRef = useRef<HTMLTextAreaElement>(null);
  const consentPromptTextAreaRef = useRef<HTMLTextAreaElement>(null);
  const customHelpLinkUrlInputRef = useRef<HTMLInputElement>(null);
  const prevShowFirstVisitNoticeRef = useRef<boolean>(
    Boolean(values.show_first_visit_notice)
  );
  const prevEnableConsentScreenRef = useRef<boolean>(
    Boolean(values.enable_consent_screen)
  );
  const [focusedPreviewTarget, setFocusedPreviewTarget] =
    useState<PreviewHighlightTarget | null>(null);
  const [hoveredPreviewTarget, setHoveredPreviewTarget] =
    useState<PreviewHighlightTarget | null>(null);

  const highlightTarget = useMemo(
    () => focusedPreviewTarget ?? hoveredPreviewTarget,
    [focusedPreviewTarget, hoveredPreviewTarget]
  );

  const getPreviewHandlers = (target: PreviewHighlightTarget) => ({
    onFocus: () => setFocusedPreviewTarget(target),
    onBlur: () =>
      setFocusedPreviewTarget((cur) => (cur === target ? null : cur)),
    onMouseEnter: () => setHoveredPreviewTarget(target),
    onMouseLeave: () =>
      setHoveredPreviewTarget((cur) => (cur === target ? null : cur)),
  });

  // Expose focusFirstError method to parent component
  useImperativeHandle(ref, () => ({
    focusFirstError: (errors: Record<string, any>) => {
      // Focus on the first field with an error, in priority order
      const fieldRefs = [
        { name: "application_name", ref: applicationNameInputRef },
        { name: "custom_greeting_message", ref: greetingMessageInputRef },
        { name: "custom_header_content", ref: headerContentInputRef },
        {
          name: "custom_lower_disclaimer_content",
          ref: lowerDisclaimerInputRef,
        },
        { name: "custom_popup_header", ref: noticeHeaderInputRef },
        { name: "custom_popup_content", ref: noticeContentInputRef },
        { name: "consent_screen_prompt", ref: consentPromptTextAreaRef },
        { name: "custom_help_link_url", ref: customHelpLinkUrlInputRef },
      ];
      for (const field of fieldRefs) {
        if (errors[field.name] && field.ref.current) {
          field.ref.current.focus();
          // Scroll into view if needed
          field.ref.current.scrollIntoView({
            behavior: "smooth",
            block: "center",
          });
          break;
        }
      }
    },
  }));

  useEffect(() => {
    const prev = prevShowFirstVisitNoticeRef.current;
    const next = Boolean(values.show_first_visit_notice);

    // When enabling the toggle, autofocus the "Notice Header" input.
    if (!prev && next) {
      requestAnimationFrame(() => {
        noticeHeaderInputRef.current?.focus();
      });
    }

    prevShowFirstVisitNoticeRef.current = next;
  }, [values.show_first_visit_notice]);

  useEffect(() => {
    const prev = prevEnableConsentScreenRef.current;
    const next = Boolean(values.enable_consent_screen);

    // When enabling the toggle, autofocus the "Notice Consent Prompt" input.
    if (!prev && next) {
      requestAnimationFrame(() => {
        consentPromptTextAreaRef.current?.focus();
      });
    }

    prevEnableConsentScreenRef.current = next;
  }, [values.enable_consent_screen]);

  const handleLogoEdit = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) {
      setSelectedLogo(file);
      setFieldValue("use_custom_logo", true);
    }
  };

  const handleLogoRemove = async () => {
    setFieldValue("use_custom_logo", false);
    setSelectedLogo(null);
  };

  // Memoize the blob URL to prevent creating new URLs on every render
  const logoObjectUrl = useMemo(() => {
    if (selectedLogo) {
      return URL.createObjectURL(selectedLogo);
    }
    return null;
  }, [selectedLogo]);

  // Clean up the blob URL when selectedLogo changes or component unmounts
  useEffect(() => {
    return () => {
      if (logoObjectUrl) {
        URL.revokeObjectURL(logoObjectUrl);
      }
    };
  }, [logoObjectUrl]);

  const logoSrc = useMemo(() => {
    if (logoObjectUrl) {
      return logoObjectUrl;
    }
    if (values.use_custom_logo) {
      return `/api/enterprise-settings/logo?v=${logoVersion}`;
    }
    return undefined;
  }, [logoObjectUrl, values.use_custom_logo, logoVersion]);

  // Determine which tabs should be enabled
  const hasLogo = Boolean(selectedLogo || values.use_custom_logo);
  const hasApplicationName = Boolean(values.application_name?.trim());

  // Auto-switch to logo_and_name if current selection becomes invalid
  useEffect(() => {
    if (values.logo_display_style === "logo_only" && !hasLogo) {
      setFieldValue("logo_display_style", "logo_and_name");
    } else if (
      values.logo_display_style === "name_only" &&
      !hasApplicationName
    ) {
      setFieldValue("logo_display_style", "logo_and_name");
    }
  }, [hasLogo, hasApplicationName, values.logo_display_style, setFieldValue]);

  return (
    <div className="flex flex-col gap-4 w-full">
      <input
        type="file"
        ref={fileInputRef}
        onChange={handleFileChange}
        accept="image/png,image/jpeg,image/jpg"
        style={{ display: "none" }}
      />

      <div className="flex gap-10 items-center">
        <div className="flex flex-col gap-4 w-full">
          <FormField state={errors.application_name ? "error" : "idle"}>
            <FormField.Label
              rightAction={
                <CharacterCount
                  value={values.application_name}
                  limit={charLimits.application_name}
                />
              }
            >
              {t("admin.theme.app_name")}
            </FormField.Label>
            <FormField.Control asChild>
              <InputTypeIn
                ref={applicationNameInputRef}
                data-label="application-name-input"
                clearButton
                variant={errors.application_name ? "error" : undefined}
                value={values.application_name}
                {...getPreviewHandlers("sidebar")}
                onChange={(e) =>
                  setFieldValue("application_name", e.target.value)
                }
              />
            </FormField.Control>
            <FormField.Description>
              {t("admin.theme.app_name_desc")}
            </FormField.Description>
            <FormField.Message
              messages={{ error: errors.application_name as string }}
            />
          </FormField>

          <FormField state="idle">
            <FormField.Label>{t("admin.theme.logo_style")}</FormField.Label>
            <FormField.Control>
              <Tabs
                value={values.logo_display_style}
                onValueChange={(value) =>
                  setFieldValue("logo_display_style", value)
                }
              >
                <Tabs.List>
                  <Tabs.Trigger
                    value="logo_and_name"
                    tooltip={t("admin.theme.tooltip_logo_and_name")}
                    tooltipSide="top"
                    {...getPreviewHandlers("sidebar")}
                  >
                    {t("admin.theme.logo_and_name")}
                  </Tabs.Trigger>
                  <Tabs.Trigger
                    value="logo_only"
                    disabled={!hasLogo}
                    tooltip={
                      hasLogo
                        ? t("admin.theme.tooltip_logo_only")
                        : t("admin.theme.tooltip_logo_only_disabled")
                    }
                    tooltipSide="top"
                    {...getPreviewHandlers("sidebar")}
                  >
                    {t("admin.theme.logo_only")}
                  </Tabs.Trigger>
                  <Tabs.Trigger
                    value="name_only"
                    disabled={!hasApplicationName}
                    tooltip={
                      hasApplicationName
                        ? t("admin.theme.tooltip_name_only")
                        : t("admin.theme.tooltip_name_only_disabled")
                    }
                    tooltipSide="top"
                    {...getPreviewHandlers("sidebar")}
                  >
                    {t("admin.theme.name_only")}
                  </Tabs.Trigger>
                </Tabs.List>
              </Tabs>
            </FormField.Control>
            <FormField.Description>
              {t("admin.theme.logo_style_desc")}
            </FormField.Description>
          </FormField>
        </div>

        <FormField state="idle">
          <FormField.Label>{t("admin.theme.app_logo")}</FormField.Label>
          <FormField.Control>
            <InputImage
              src={logoSrc}
              onEdit={handleLogoEdit}
              onDrop={(file) => {
                setSelectedLogo(file);
                setFieldValue("use_custom_logo", true);
              }}
              onRemove={handleLogoRemove}
              showEditOverlay={false}
            />
          </FormField.Control>
          <div className="mt-2 w-full justify-center items-center flex">
            <Button
              disabled={!hasLogo}
              prominence="secondary"
              onClick={handleLogoEdit}
              icon={SvgEdit}
            >
              {t("admin.theme.update_btn")}
            </Button>
          </div>
        </FormField>
      </div>

      <Divider />

      <Preview
        className="mb-8"
        logoDisplayStyle={values.logo_display_style}
        applicationDisplayName={values.application_name ?? ""}
        chat_footer_content={
          values.custom_lower_disclaimer_content || "Chat Footer Content"
        }
        chat_header_content={
          values.custom_header_content || "Chat Header Content"
        }
        greeting_message={
          values.custom_greeting_message || "Welcome to Acme Chat"
        }
        logoSrc={logoSrc}
        highlightTarget={highlightTarget}
      />

      <FormField state={errors.custom_greeting_message ? "error" : "idle"}>
        <FormField.Label
          rightAction={
            <CharacterCount
              value={values.custom_greeting_message}
              limit={charLimits.custom_greeting_message}
            />
          }
        >
          {t("admin.theme.greeting")}
        </FormField.Label>
        <FormField.Control asChild>
          <InputTypeIn
            ref={greetingMessageInputRef}
            data-label="greeting-message-input"
            clearButton
            variant={errors.custom_greeting_message ? "error" : undefined}
            value={values.custom_greeting_message}
            {...getPreviewHandlers("greeting")}
            onChange={(e) =>
              setFieldValue("custom_greeting_message", e.target.value)
            }
          />
        </FormField.Control>
        <FormField.Description>
          {t("admin.theme.greeting_desc")}
        </FormField.Description>
        <FormField.Message
          messages={{ error: errors.custom_greeting_message as string }}
        />
      </FormField>

      <FormField state={errors.custom_header_content ? "error" : "idle"}>
        <FormField.Label
          rightAction={
            <CharacterCount
              value={values.custom_header_content}
              limit={charLimits.custom_header_content}
            />
          }
        >
          {t("admin.theme.header_text")}
        </FormField.Label>
        <FormField.Control asChild>
          <InputTypeIn
            ref={headerContentInputRef}
            data-label="chat-header-input"
            clearButton
            variant={errors.custom_header_content ? "error" : undefined}
            value={values.custom_header_content}
            {...getPreviewHandlers("chat_header")}
            onChange={(e) =>
              setFieldValue("custom_header_content", e.target.value)
            }
          />
        </FormField.Control>
        <FormField.Message
          messages={{ error: errors.custom_header_content as string }}
        />
      </FormField>

      <FormField
        state={errors.custom_lower_disclaimer_content ? "error" : "idle"}
      >
        <FormField.Label
          rightAction={
            <CharacterCount
              value={values.custom_lower_disclaimer_content}
              limit={charLimits.custom_lower_disclaimer_content}
            />
          }
        >
          {t("admin.theme.footer_text")}
        </FormField.Label>
        <FormField.Control asChild>
          <InputTextArea
            ref={lowerDisclaimerInputRef}
            data-label="chat-footer-textarea"
            rows={3}
            placeholder={t("admin.theme.add_markdown_placeholder")}
            variant={
              errors.custom_lower_disclaimer_content ? "error" : undefined
            }
            value={values.custom_lower_disclaimer_content}
            {...getPreviewHandlers("chat_footer")}
            onChange={(e) =>
              setFieldValue("custom_lower_disclaimer_content", e.target.value)
            }
          />
        </FormField.Control>
        <FormField.Description>
          {t("admin.theme.footer_text_desc")}
        </FormField.Description>
        <FormField.Message
          messages={{ error: errors.custom_lower_disclaimer_content as string }}
        />
      </FormField>

      <Disabled
        disabled={!enterpriseTier}
        tooltip={t("admin.theme.help_link_disabled_tooltip")}
      >
        <div className="flex gap-2 items-start">
          <FormField
            state={errors.custom_help_link_url ? "error" : "idle"}
            className="flex-1"
          >
            <FormField.Label>
              {t("admin.theme.help_link")}
              {!enterpriseTier && (
                <Tag {...planTagProps("enterprise")} size="sm" />
              )}
            </FormField.Label>
            <FormField.Control asChild>
              <InputTypeIn
                ref={customHelpLinkUrlInputRef}
                data-label="custom-help-link-url-input"
                clearButton
                placeholder="https://docs.onyx.app"
                variant={
                  !enterpriseTier
                    ? "disabled"
                    : errors.custom_help_link_url
                      ? "error"
                      : undefined
                }
                value={values.custom_help_link_url}
                onChange={(e) =>
                  setFieldValue("custom_help_link_url", e.target.value)
                }
              />
            </FormField.Control>
            <FormField.Description>
              {t("admin.theme.help_link_desc")}
            </FormField.Description>
            <FormField.Message
              messages={{ error: errors.custom_help_link_url as string }}
            />
          </FormField>
          <FormField state="idle" className="flex-1">
            <FormField.Label className="invisible" aria-hidden="true">
              Custom Help Link Label
            </FormField.Label>
            <FormField.Control asChild>
              <InputTypeIn
                aria-label="Custom Help Link Label"
                data-label="custom-help-link-label-input"
                clearButton
                placeholder={t("admin.theme.help_link_label_placeholder")}
                variant={!enterpriseTier ? "disabled" : undefined}
                value={values.custom_help_link_label}
                onChange={(e) =>
                  setFieldValue("custom_help_link_label", e.target.value)
                }
              />
            </FormField.Control>
          </FormField>
        </div>
      </Disabled>

      <Disabled
        disabled={!enterpriseTier}
        tooltip={t("admin.theme.hide_branding_disabled_tooltip")}
      >
        <FormField state="idle" className="gap-0">
          <div className="flex justify-between items-center">
            <FormField.Label>
              {t("admin.theme.hide_branding")}
              {!enterpriseTier && (
                <Tag {...planTagProps("enterprise")} size="sm" />
              )}
            </FormField.Label>
            <FormField.Control>
              <Switch
                aria-label="Hide Onyx Branding"
                data-label="hide-onyx-branding-toggle"
                checked={values.hide_onyx_branding}
                onCheckedChange={(checked) =>
                  setFieldValue("hide_onyx_branding", checked)
                }
                disabled={!enterpriseTier}
              />
            </FormField.Control>
          </div>
          <FormField.Description>
            {t("admin.theme.hide_branding_desc")}
          </FormField.Description>
        </FormField>
      </Disabled>

      <Divider />

      <div className="flex flex-col gap-4 p-4 bg-background-tint-00 rounded-16">
        <FormField state="idle" className="gap-0">
          <div className="flex justify-between items-center">
            <FormField.Label>{t("admin.theme.first_visit")}</FormField.Label>
            <FormField.Control>
              <Switch
                aria-label="Show First Visit Notice"
                data-label="first-visit-notice-toggle"
                checked={values.show_first_visit_notice}
                onCheckedChange={(checked) =>
                  setFieldValue("show_first_visit_notice", checked)
                }
              />
            </FormField.Control>
          </div>
          <FormField.Description>
            {t("admin.theme.first_visit_desc")}
          </FormField.Description>
        </FormField>

        {values.show_first_visit_notice && (
          <>
            <FormField state={errors.custom_popup_header ? "error" : "idle"}>
              <FormField.Label
                required
                rightAction={
                  <CharacterCount
                    value={values.custom_popup_header}
                    limit={charLimits.custom_popup_header}
                  />
                }
              >
                {t("admin.theme.notice_header")}
              </FormField.Label>
              <FormField.Control asChild>
                <InputTypeIn
                  ref={noticeHeaderInputRef}
                  data-label="notice-header-input"
                  clearButton
                  variant={errors.custom_popup_header ? "error" : undefined}
                  value={values.custom_popup_header}
                  onChange={(e) =>
                    setFieldValue("custom_popup_header", e.target.value)
                  }
                />
              </FormField.Control>
              <FormField.Message
                messages={{ error: errors.custom_popup_header as string }}
              />
            </FormField>

            <FormField state={errors.custom_popup_content ? "error" : "idle"}>
              <FormField.Label
                required
                rightAction={
                  <CharacterCount
                    value={values.custom_popup_content}
                    limit={charLimits.custom_popup_content}
                  />
                }
              >
                {t("admin.theme.notice_content")}
              </FormField.Label>
              <FormField.Control asChild>
                <InputTextArea
                  ref={noticeContentInputRef}
                  data-label="notice-content-textarea"
                  rows={3}
                  placeholder={t("admin.theme.add_markdown_placeholder")}
                  variant={errors.custom_popup_content ? "error" : undefined}
                  value={values.custom_popup_content}
                  onChange={(e) =>
                    setFieldValue("custom_popup_content", e.target.value)
                  }
                />
              </FormField.Control>
              <FormField.Message
                messages={{ error: errors.custom_popup_content as string }}
              />
            </FormField>

            <FormField state="idle" className="gap-0">
              <div className="flex justify-between items-center">
                <FormField.Label>{t("admin.theme.require_consent")}</FormField.Label>
                <FormField.Control>
                  <Switch
                    aria-label="Require Consent to Notice"
                    data-label="require-consent-toggle"
                    checked={values.enable_consent_screen}
                    onCheckedChange={(checked) =>
                      setFieldValue("enable_consent_screen", checked)
                    }
                  />
                </FormField.Control>
              </div>
              <FormField.Description>
                {t("admin.theme.require_consent_desc")}
              </FormField.Description>
            </FormField>

            {values.enable_consent_screen && (
              <FormField
                state={errors.consent_screen_prompt ? "error" : "idle"}
              >
                <FormField.Label
                  required
                  rightAction={
                    <CharacterCount
                      value={values.consent_screen_prompt}
                      limit={charLimits.consent_screen_prompt}
                    />
                  }
                >
                  {t("admin.theme.consent_prompt")}
                </FormField.Label>
                <FormField.Control asChild>
                  <InputTextArea
                    ref={consentPromptTextAreaRef}
                    data-label="consent-prompt-textarea"
                    rows={3}
                    placeholder={t("admin.theme.add_markdown_placeholder")}
                    variant={errors.consent_screen_prompt ? "error" : undefined}
                    value={values.consent_screen_prompt}
                    onChange={(e) => {
                      setFieldValue("consent_screen_prompt", e.target.value);
                    }}
                  />
                </FormField.Control>
                <FormField.Message
                  messages={{ error: errors.consent_screen_prompt as string }}
                />
              </FormField>
            )}
          </>
        )}
      </div>
    </div>
  );
});
