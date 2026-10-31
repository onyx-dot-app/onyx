"use client";

import { Modal, Text } from "@opal/components";
import { richNodes } from "@opal/utils";
import { useSettings } from "@/lib/settings/hooks";
import { Button } from "@opal/components";
import { FormField } from "@/refresh-components/form/FormField";
import { InputCheckbox } from "@opal/components";
import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { transformLinkUri } from "@/lib/utils";
import { SvgAlertCircle } from "@opal/icons";
import { SvgOnyxLogo } from "@opal/logos";
import type { IconProps } from "@opal/types";
import { useTranslations } from "next-intl";

const ALL_USERS_INITIAL_POPUP_FLOW_COMPLETED =
  "allUsersInitialPopupFlowCompleted";

const CustomLogoHeaderIcon = ({ className, size = 24 }: IconProps) => {
  const t = useTranslations("chat.popup");

  return (
    <img
      src="/api/enterprise-settings/logo"
      alt={t("logoIcon.alt")}
      style={{ width: size, height: size, objectFit: "contain" }}
      className={className}
    />
  );
};

export function AppPopup() {
  const t = useTranslations("chat.popup");
  const [completedFlow, setCompletedFlow] = useState(true);
  const [showConsentError, setShowConsentError] = useState(false);
  const [consentChecked, setConsentChecked] = useState(false);

  useEffect(() => {
    setCompletedFlow(
      localStorage.getItem(ALL_USERS_INITIAL_POPUP_FLOW_COMPLETED) === "true"
    );
  }, []);

  const settings = useSettings();
  const isConsentScreen = settings.enterprise?.enable_consent_screen;

  if (
    !settings.enterprise?.custom_popup_content ||
    completedFlow ||
    !settings.enterprise?.show_first_visit_notice
  ) {
    return null;
  }

  const popupTitle = settings.enterprise?.custom_popup_header;

  const popupContent = settings.enterprise?.custom_popup_content;

  const hasApplicationName = Boolean(
    settings.enterprise?.application_name?.trim()
  );
  const hasCustomLogo = Boolean(settings.enterprise?.use_custom_logo);
  const logoDisplayStyle = settings.enterprise?.logo_display_style;

  // Header icon rules:
  // - If neither app name nor custom logo exists -> show Onyx icon
  // - If logo display is "name_only" -> show alert icon
  // - Otherwise -> show uploaded custom logo (fallback to Onyx icon)
  const headerIcon =
    !hasApplicationName && !hasCustomLogo
      ? (props: IconProps) => <SvgOnyxLogo size={24} {...props} />
      : logoDisplayStyle === "name_only"
        ? SvgAlertCircle
        : hasCustomLogo
          ? CustomLogoHeaderIcon
          : (props: IconProps) => <SvgOnyxLogo size={24} {...props} />;

  return (
    <Modal open onOpenChange={() => {}}>
      <Modal.Content width="sm" height="lg">
        <Modal.Header
          icon={headerIcon}
          title={popupTitle || t("header.title", { appName: settings.appName })}
        />
        <Modal.Body>
          <div className="overflow-y-auto text-start">
            <ReactMarkdown
              className="prose prose-neutral dark:prose-invert max-w-full"
              components={{
                a: ({ node, children, ...props }) => (
                  <a
                    {...props}
                    className="text-link hover:text-link-hover"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {children}
                  </a>
                ),
                p: ({ children }) => (
                  <Text as="p" font="main-ui-body" color="text-03">
                    {richNodes(children)}
                  </Text>
                ),
                strong: ({ children }) => (
                  <Text font="main-ui-body" color="text-03">
                    {richNodes(children)}
                  </Text>
                ),
                h1: ({ children }) => (
                  <Text as="p" font="heading-h1" color="text-03">
                    {richNodes(children)}
                  </Text>
                ),
                h2: ({ children }) => (
                  <Text as="p" font="heading-h2" color="text-03">
                    {richNodes(children)}
                  </Text>
                ),
                h3: ({ children }) => (
                  <Text as="p" font="heading-h3" color="text-03">
                    {richNodes(children)}
                  </Text>
                ),
                li: ({ children }) => (
                  <Text as="li" font="main-ui-body" color="text-03">
                    {richNodes(children)}
                  </Text>
                ),
              }}
              remarkPlugins={[remarkGfm]}
              urlTransform={transformLinkUri}
            >
              {popupContent}
            </ReactMarkdown>
            {isConsentScreen && settings.enterprise?.consent_screen_prompt && (
              <FormField
                state={showConsentError ? "error" : "idle"}
                className="mt-6"
              >
                <div className="flex items-center gap-1">
                  <FormField.Control>
                    <InputCheckbox
                      aria-label={t("consentCheckbox.label")}
                      checked={consentChecked}
                      onCheckedChange={(checked) => {
                        setConsentChecked(checked);
                        if (checked) {
                          setShowConsentError(false);
                        }
                      }}
                    />
                  </FormField.Control>
                  <FormField.Label>
                    <ReactMarkdown
                      // [&_p]:my-0! keeps the markdown aligned with the checkbox.
                      className="prose prose-neutral dark:prose-invert max-w-full [&_p]:my-0!"
                      components={{
                        a: ({ node, children, ...props }) => (
                          <a
                            {...props}
                            className="text-link hover:text-link-hover"
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            {children}
                          </a>
                        ),
                        p: ({ children }) => (
                          <Text as="p" font="main-ui-body" color="text-04">
                            {richNodes(children)}
                          </Text>
                        ),
                        strong: ({ children }) => (
                          <Text font="main-ui-body" color="text-04">
                            {richNodes(children)}
                          </Text>
                        ),
                        li: ({ children }) => (
                          <Text as="li" font="main-ui-body" color="text-04">
                            {richNodes(children)}
                          </Text>
                        ),
                      }}
                      remarkPlugins={[remarkGfm]}
                      urlTransform={transformLinkUri}
                    >
                      {settings.enterprise.consent_screen_prompt}
                    </ReactMarkdown>
                  </FormField.Label>
                </div>
                <FormField.Message
                  messages={{ error: t("consentRequired.error") }}
                />
              </FormField>
            )}
          </div>
        </Modal.Body>
        <Modal.Footer>
          <Button
            onClick={() => {
              if (isConsentScreen && !consentChecked) {
                setShowConsentError(true);
                return;
              }
              localStorage.setItem(
                ALL_USERS_INITIAL_POPUP_FLOW_COMPLETED,
                "true"
              );
              setCompletedFlow(true);
            }}
          >
            {t("startButton.label")}
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
