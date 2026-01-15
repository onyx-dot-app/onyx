"use client";

import Modal from "@/refresh-components/Modal";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import { FormField } from "@/refresh-components/form/FormField";
import Checkbox from "@/refresh-components/inputs/Checkbox";
import { useContext, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { transformLinkUri } from "@/lib/utils";
import { SvgAlertCircle } from "@opal/icons";
import { IconProps, OnyxIcon } from "@/components/icons/icons";

const ALL_USERS_INITIAL_POPUP_FLOW_COMPLETED =
  "allUsersInitialPopupFlowCompleted";

const CustomLogoHeaderIcon = ({ className, size = 24 }: IconProps) => (
  <img
    src="/api/enterprise-settings/logo"
    alt="Logo"
    style={{ width: size, height: size, objectFit: "contain" }}
    className={className}
  />
);

export function ChatPopup() {
  const [completedFlow, setCompletedFlow] = useState(true);
  const [showConsentError, setShowConsentError] = useState(false);
  const [consentChecked, setConsentChecked] = useState(false);

  useEffect(() => {
    setCompletedFlow(
      localStorage.getItem(ALL_USERS_INITIAL_POPUP_FLOW_COMPLETED) === "true"
    );
  }, []);

  const settings = useContext(SettingsContext);
  const enterpriseSettings = settings?.enterpriseSettings;
  const isConsentScreen = enterpriseSettings?.enable_consent_screen;

  if (
    !enterpriseSettings?.custom_popup_content ||
    completedFlow ||
    !enterpriseSettings?.show_first_visit_notice
  ) {
    return null;
  }

  const popupTitle = enterpriseSettings?.custom_popup_header;

  const popupContent = enterpriseSettings?.custom_popup_content;

  const hasApplicationName = Boolean(
    enterpriseSettings?.application_name?.trim()
  );
  const hasCustomLogo = Boolean(enterpriseSettings?.use_custom_logo);
  const logoDisplayStyle = enterpriseSettings?.logo_display_style;

  // Header icon rules:
  // - If neither app name nor custom logo exists -> show Onyx icon
  // - If logo display is "name_only" -> show alert icon
  // - Otherwise -> show uploaded custom logo (fallback to Onyx icon)
  const headerIcon =
    !hasApplicationName && !hasCustomLogo
      ? (props: IconProps) => <OnyxIcon size={24} {...props} />
      : logoDisplayStyle === "name_only"
        ? SvgAlertCircle
        : hasCustomLogo
          ? CustomLogoHeaderIcon
          : (props: IconProps) => <OnyxIcon size={24} {...props} />;

  return (
    <Modal open onOpenChange={() => {}}>
      <Modal.Content tall>
        <Modal.Header
          titleClassName="text-text-04"
          icon={headerIcon}
          title={popupTitle || "Welcome to Onyx!"}
        />
        <Modal.Body>
          <div className="overflow-y-auto text-left">
            <ReactMarkdown
              className="prose prose-neutral dark:prose-invert max-w-full"
              components={{
                a: ({ node, ...props }) => (
                  <a
                    {...props}
                    className="text-link hover:text-link-hover"
                    target="_blank"
                    rel="noopener noreferrer"
                  />
                ),
                p: ({ node, ...props }) => (
                  <Text as="p" mainUiBody text03 {...props} />
                ),
                strong: ({ node, ...props }) => (
                  <Text as="span" mainUiBody text03 {...props} />
                ),
                h1: ({ node, ...props }) => (
                  <Text as="p" headingH1 text03 {...props} />
                ),
                h2: ({ node, ...props }) => (
                  <Text as="p" headingH2 text03 {...props} />
                ),
                h3: ({ node, ...props }) => (
                  <Text as="p" headingH3 text03 {...props} />
                ),
                li: ({ node, ...props }) => (
                  <Text as="li" mainUiBody text03 {...props} />
                ),
              }}
              remarkPlugins={[remarkGfm]}
              urlTransform={transformLinkUri}
            >
              {popupContent}
            </ReactMarkdown>
            {isConsentScreen && enterpriseSettings?.consent_screen_prompt && (
              <FormField
                state={showConsentError ? "error" : "idle"}
                className="mt-6"
              >
                <div className="flex items-center gap-1">
                  <FormField.Control>
                    <Checkbox
                      aria-label="Consent checkbox"
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
                      className="prose prose-neutral dark:prose-invert max-w-full"
                      components={{
                        a: ({ node, ...props }) => (
                          <a
                            {...props}
                            className="text-link hover:text-link-hover"
                            target="_blank"
                            rel="noopener noreferrer"
                          />
                        ),
                        p: ({ node, ...props }) => (
                          <Text
                            as="p"
                            mainUiBody
                            text04
                            className="!my-0" //dont remove the !my-0 class, it's important for the markdown to render without any alignment issues
                            {...props}
                          />
                        ),
                        strong: ({ node, ...props }) => (
                          <Text as="span" mainUiBody text04 {...props} />
                        ),
                        li: ({ node, ...props }) => (
                          <Text as="li" mainUiBody text04 {...props} />
                        ),
                      }}
                      remarkPlugins={[remarkGfm]}
                      urlTransform={transformLinkUri}
                    >
                      {enterpriseSettings.consent_screen_prompt}
                    </ReactMarkdown>
                  </FormField.Label>
                </div>
                <FormField.Message
                  messages={{
                    error:
                      "You need to agree to the terms to access the application.",
                  }}
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
            Start
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
