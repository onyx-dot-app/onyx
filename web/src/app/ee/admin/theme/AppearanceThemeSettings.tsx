"use client";

import { FormField } from "@/refresh-components/form/FormField";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { Tabs, TabsList, TabsTrigger } from "@/refresh-components/tabs/tabs";
import Separator from "@/refresh-components/Separator";
import { Preview } from "./Preview";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";
import Switch from "@/refresh-components/inputs/Switch";
import CharacterCount from "@/refresh-components/CharacterCount";
import InputImage from "@/refresh-components/inputs/InputImage";
import Button from "@/refresh-components/buttons/Button";
import { useFormikContext } from "formik";
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

interface AppearanceThemeSettingsProps {
  selectedLogo: File | null;
  setSelectedLogo: (file: File | null) => void;
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
  { selectedLogo, setSelectedLogo, charLimits },
  ref
) {
  const { values, errors, setFieldValue } = useFormikContext<any>();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const applicationNameInputRef = useRef<HTMLInputElement>(null);
  const greetingMessageInputRef = useRef<HTMLInputElement>(null);
  const headerContentInputRef = useRef<HTMLInputElement>(null);
  const lowerDisclaimerInputRef = useRef<HTMLTextAreaElement>(null);
  const noticeHeaderInputRef = useRef<HTMLInputElement>(null);
  const noticeContentInputRef = useRef<HTMLTextAreaElement>(null);
  const consentPromptTextAreaRef = useRef<HTMLTextAreaElement>(null);
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

  const getLogoSrc = () => {
    if (logoObjectUrl) {
      return logoObjectUrl;
    }
    if (values.use_custom_logo) {
      return `/api/enterprise-settings/logo?u=${Date.now()}`;
    }
    return undefined;
  };

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
              Application Display Name
            </FormField.Label>
            <FormField.Control asChild>
              <InputTypeIn
                ref={applicationNameInputRef}
                data-label="application-name-input"
                showClearButton
                error={!!errors.application_name}
                value={values.application_name}
                {...getPreviewHandlers("sidebar")}
                onChange={(e) =>
                  setFieldValue("application_name", e.target.value)
                }
              />
            </FormField.Control>
            <FormField.Description>
              This name will show across the app and replace "Onyx" in the UI.
            </FormField.Description>
            <FormField.Message
              messages={{ error: errors.application_name as string }}
            />
          </FormField>

          <FormField state="idle">
            <FormField.Label>Logo Display Style</FormField.Label>
            <FormField.Control>
              <Tabs
                value={values.logo_display_style}
                onValueChange={(value) =>
                  setFieldValue("logo_display_style", value)
                }
              >
                <TabsList className="w-full grid grid-cols-3">
                  <TabsTrigger
                    value="logo_and_name"
                    tooltip="Show both your application logo and name."
                    tooltipSide="top"
                    {...getPreviewHandlers("sidebar")}
                  >
                    Logo & Name
                  </TabsTrigger>
                  <TabsTrigger
                    value="logo_only"
                    disabled={!hasLogo}
                    tooltip={
                      hasLogo
                        ? "Show only your application logo."
                        : "Upload a logo to enable this option."
                    }
                    tooltipSide="top"
                    {...getPreviewHandlers("sidebar")}
                  >
                    Logo Only
                  </TabsTrigger>
                  <TabsTrigger
                    value="name_only"
                    disabled={!hasApplicationName}
                    tooltip={
                      hasApplicationName
                        ? "Show only your application name."
                        : "Enter an application name to enable this option."
                    }
                    tooltipSide="top"
                    {...getPreviewHandlers("sidebar")}
                  >
                    Name Only
                  </TabsTrigger>
                </TabsList>
              </Tabs>
            </FormField.Control>
            <FormField.Description>
              Choose what to display at the top of the sidebar. Options become
              available once you add a logo or application name.
            </FormField.Description>
          </FormField>
        </div>

        <FormField state="idle">
          <FormField.Label>Application Logo</FormField.Label>
          <FormField.Control>
            <InputImage
              src={getLogoSrc()}
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
              secondary
              disabled={!hasLogo}
              onClick={handleLogoEdit}
              leftIcon={SvgEdit}
            >
              Update
            </Button>
          </div>
        </FormField>
      </div>

      <Separator className="my-4" />

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
        logoSrc={getLogoSrc()}
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
          Greeting Message
        </FormField.Label>
        <FormField.Control asChild>
          <InputTypeIn
            ref={greetingMessageInputRef}
            data-label="greeting-message-input"
            showClearButton
            error={!!errors.custom_greeting_message}
            value={values.custom_greeting_message}
            {...getPreviewHandlers("greeting")}
            onChange={(e) =>
              setFieldValue("custom_greeting_message", e.target.value)
            }
          />
        </FormField.Control>
        <FormField.Description>
          Add a short message to the home page.
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
          Chat Header Text
        </FormField.Label>
        <FormField.Control asChild>
          <InputTypeIn
            ref={headerContentInputRef}
            data-label="chat-header-input"
            showClearButton
            error={!!errors.custom_header_content}
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
          Chat Footer Text
        </FormField.Label>
        <FormField.Control asChild>
          <InputTextArea
            ref={lowerDisclaimerInputRef}
            data-label="chat-footer-textarea"
            rows={3}
            placeholder="Add markdown content"
            error={!!errors.custom_lower_disclaimer_content}
            value={values.custom_lower_disclaimer_content}
            {...getPreviewHandlers("chat_footer")}
            onChange={(e) =>
              setFieldValue("custom_lower_disclaimer_content", e.target.value)
            }
          />
        </FormField.Control>
        <FormField.Description>
          Add markdown content for disclaimers or additional information.
        </FormField.Description>
        <FormField.Message
          messages={{ error: errors.custom_lower_disclaimer_content as string }}
        />
      </FormField>

      <Separator className="my-4" />

      <div className="flex flex-col gap-4 p-4 bg-background-tint-00 rounded-16">
        <FormField state="idle" className="gap-0">
          <div className="flex justify-between items-center">
            <FormField.Label>Show First Visit Notice</FormField.Label>
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
            Show a one-time pop-up for new users at their first visit.
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
                Notice Header
              </FormField.Label>
              <FormField.Control asChild>
                <InputTypeIn
                  ref={noticeHeaderInputRef}
                  data-label="notice-header-input"
                  showClearButton
                  error={!!errors.custom_popup_header}
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
                Notice Content
              </FormField.Label>
              <FormField.Control asChild>
                <InputTextArea
                  ref={noticeContentInputRef}
                  data-label="notice-content-textarea"
                  rows={3}
                  placeholder="Add markdown content"
                  error={!!errors.custom_popup_content}
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
                <FormField.Label>Require Consent to Notice</FormField.Label>
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
                Require the user to read and agree to the notice before
                accessing the application.
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
                  Notice Consent Prompt
                </FormField.Label>
                <FormField.Control asChild>
                  <InputTextArea
                    ref={consentPromptTextAreaRef}
                    data-label="consent-prompt-textarea"
                    rows={3}
                    placeholder="Add markdown content"
                    error={!!errors.consent_screen_prompt}
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
