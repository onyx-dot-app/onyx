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
import { Preview } from "./Preview";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";
import CharacterCount from "@/refresh-components/CharacterCount";
import InputImage from "@/refresh-components/inputs/InputImage";
import { Disabled } from "@opal/core";
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
import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { Tier } from "@/interfaces/settings";
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
              应用显示名称
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
              此名称会显示在应用各处，并替换界面中的“Glomi AI”。
            </FormField.Description>
            <FormField.Message
              messages={{ error: errors.application_name as string }}
            />
          </FormField>

          <FormField state="idle">
            <FormField.Label>Logo 显示样式</FormField.Label>
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
                    tooltip="同时显示应用 Logo 和名称。"
                    tooltipSide="top"
                    {...getPreviewHandlers("sidebar")}
                  >
                    Logo 和名称
                  </Tabs.Trigger>
                  <Tabs.Trigger
                    value="logo_only"
                    disabled={!hasLogo}
                    tooltip={
                      hasLogo
                        ? "仅显示应用 Logo。"
                        : "上传 Logo 后可启用此选项。"
                    }
                    tooltipSide="top"
                    {...getPreviewHandlers("sidebar")}
                  >
                    仅 Logo
                  </Tabs.Trigger>
                  <Tabs.Trigger
                    value="name_only"
                    disabled={!hasApplicationName}
                    tooltip={
                      hasApplicationName
                        ? "仅显示应用名称。"
                        : "输入应用名称后可启用此选项。"
                    }
                    tooltipSide="top"
                    {...getPreviewHandlers("sidebar")}
                  >
                    仅名称
                  </Tabs.Trigger>
                </Tabs.List>
              </Tabs>
            </FormField.Control>
            <FormField.Description>
              选择侧边栏顶部显示的内容。添加 Logo 或应用名称后，相关选项会变为可用。
            </FormField.Description>
          </FormField>
        </div>

        <FormField state="idle">
          <FormField.Label>应用 Logo</FormField.Label>
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
              更新
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
          values.custom_lower_disclaimer_content || "聊天页底部内容"
        }
        chat_header_content={
          values.custom_header_content || "聊天页顶部内容"
        }
        greeting_message={
          values.custom_greeting_message || "欢迎使用 Glomi AI"
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
          欢迎语
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
          向首页添加一条简短欢迎语。
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
          聊天页顶部文本
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
          聊天页底部文本
        </FormField.Label>
        <FormField.Control asChild>
          <InputTextArea
            ref={lowerDisclaimerInputRef}
            data-label="chat-footer-textarea"
            rows={3}
            placeholder="添加 Markdown 内容"
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
          添加免责声明或补充信息的 Markdown 内容。
        </FormField.Description>
        <FormField.Message
          messages={{ error: errors.custom_lower_disclaimer_content as string }}
        />
      </FormField>

      <Disabled
        disabled={!enterpriseTier}
        tooltip="自定义帮助链接是企业版功能。"
      >
        <div className="flex gap-2 items-start">
          <FormField
            state={errors.custom_help_link_url ? "error" : "idle"}
            className="flex-1"
          >
            <FormField.Label>
              自定义帮助链接
              {!enterpriseTier && (
                <Tag {...planTagProps("enterprise")} size="sm" />
              )}
            </FormField.Label>
            <FormField.Control asChild>
              <InputTypeIn
                ref={customHelpLinkUrlInputRef}
                data-label="custom-help-link-url-input"
                clearButton
                placeholder="https://docs.glomi.ai"
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
              在用户菜单中添加自定义帮助链接，并保留 Glomi AI 文档入口。
            </FormField.Description>
            <FormField.Message
              messages={{ error: errors.custom_help_link_url as string }}
            />
          </FormField>
          <FormField state="idle" className="flex-1">
            <FormField.Label className="invisible" aria-hidden="true">
              自定义帮助链接标签
            </FormField.Label>
            <FormField.Control asChild>
              <InputTypeIn
                aria-label="自定义帮助链接标签"
                data-label="custom-help-link-label-input"
                clearButton
                placeholder="链接标签"
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
        tooltip="隐藏 Glomi AI 品牌是企业版功能。"
      >
        <FormField state="idle" className="gap-0">
          <div className="flex justify-between items-center">
            <FormField.Label>
              隐藏 Glomi AI 品牌
              {!enterpriseTier && (
                <Tag {...planTagProps("enterprise")} size="sm" />
              )}
            </FormField.Label>
            <FormField.Control>
              <Switch
                aria-label="隐藏 Glomi AI 品牌"
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
            移除 &ldquo;由 Glomi AI 提供支持&rdquo; 以及应用中的其他 Glomi AI 品牌露出。
          </FormField.Description>
        </FormField>
      </Disabled>

      <Divider />

      <div className="flex flex-col gap-4 p-4 bg-background-tint-00 rounded-16">
        <FormField state="idle" className="gap-0">
          <div className="flex justify-between items-center">
            <FormField.Label>显示首次访问通知</FormField.Label>
            <FormField.Control>
              <Switch
                aria-label="显示首次访问通知"
                data-label="first-visit-notice-toggle"
                checked={values.show_first_visit_notice}
                onCheckedChange={(checked) =>
                  setFieldValue("show_first_visit_notice", checked)
                }
              />
            </FormField.Control>
          </div>
          <FormField.Description>
            新用户首次访问时显示一次性弹窗。
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
                通知标题
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
                通知内容
              </FormField.Label>
              <FormField.Control asChild>
                <InputTextArea
                  ref={noticeContentInputRef}
                  data-label="notice-content-textarea"
                  rows={3}
                  placeholder="添加 Markdown 内容"
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
                <FormField.Label>要求同意通知</FormField.Label>
                <FormField.Control>
                  <Switch
                    aria-label="要求同意通知"
                    data-label="require-consent-toggle"
                    checked={values.enable_consent_screen}
                    onCheckedChange={(checked) =>
                      setFieldValue("enable_consent_screen", checked)
                    }
                  />
                </FormField.Control>
              </div>
              <FormField.Description>
                要求用户在访问应用前阅读并同意通知内容。
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
                  通知同意提示
                </FormField.Label>
                <FormField.Control asChild>
                  <InputTextArea
                    ref={consentPromptTextAreaRef}
                    data-label="consent-prompt-textarea"
                    rows={3}
                    placeholder="添加 Markdown 内容"
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
