"use client";

import { useRouter } from "next/navigation";
import { EnterpriseSettings } from "@/app/admin/settings/interfaces";
import { useContext, useState } from "react";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { Form, Formik } from "formik";
import * as Yup from "yup";
import {
  BooleanFormField,
  Label,
  SubLabel,
  TextFormField,
} from "@/components/admin/connectors/Field";
import { Button } from "@/components/ui/button";
import Text from "@/components/ui/text";
import { ImageUpload } from "./ImageUpload";
import { AdvancedOptionsToggle } from "@/components/AdvancedOptionsToggle";
import Link from "next/link";
import { Separator } from "@/components/ui/separator";

export function WhitelabelingForm() {
  const router = useRouter();
  const [selectedLogo, setSelectedLogo] = useState<File | null>(null);
  const [selectedLogotype, setSelectedLogotype] = useState<File | null>(null);

  const [showAdvancedOptions, setShowAdvancedOptions] = useState(false);

  const settings = useContext(SettingsContext);
  if (!settings) {
    return null;
  }
  const enterpriseSettings = settings.enterpriseSettings;

  async function updateEnterpriseSettings(newValues: EnterpriseSettings) {
    const response = await fetch("/api/admin/enterprise-settings", {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        ...(enterpriseSettings || {}),
        ...newValues,
      }),
    });
    if (response.ok) {
      router.refresh();
    } else {
      const errorMsg = (await response.json()).detail;
      alert(`Failed to update settings. ${errorMsg}`);
    }
  }

  return (
    <div>
      <Formik
        initialValues={{
          application_name: enterpriseSettings?.application_name || null,
          use_custom_logo: enterpriseSettings?.use_custom_logo || false,
          use_custom_logotype: enterpriseSettings?.use_custom_logotype || false,
          two_lines_for_chat_header:
            enterpriseSettings?.two_lines_for_chat_header || false,
          custom_header_content:
            enterpriseSettings?.custom_header_content || "",
          custom_popup_header: enterpriseSettings?.custom_popup_header || "",
          custom_popup_content: enterpriseSettings?.custom_popup_content || "",
          custom_lower_disclaimer_content:
            enterpriseSettings?.custom_lower_disclaimer_content || "",
          custom_nav_items: enterpriseSettings?.custom_nav_items || [],
          enable_consent_screen:
            enterpriseSettings?.enable_consent_screen || false,
        }}
        validationSchema={Yup.object().shape({
          application_name: Yup.string().nullable(),
          use_custom_logo: Yup.boolean().required(),
          use_custom_logotype: Yup.boolean().required(),
          custom_header_content: Yup.string().nullable(),
          two_lines_for_chat_header: Yup.boolean().nullable(),
          custom_popup_header: Yup.string().nullable(),
          custom_popup_content: Yup.string().nullable(),
          custom_lower_disclaimer_content: Yup.string().nullable(),
          enable_consent_screen: Yup.boolean().nullable(),
        })}
        onSubmit={async (values, formikHelpers) => {
          formikHelpers.setSubmitting(true);

          if (selectedLogo) {
            values.use_custom_logo = true;

            const formData = new FormData();
            formData.append("file", selectedLogo);
            setSelectedLogo(null);
            const response = await fetch(
              "/api/admin/enterprise-settings/logo",
              {
                method: "PUT",
                body: formData,
              }
            );
            if (!response.ok) {
              const errorMsg = (await response.json()).detail;
              alert(`Failed to upload logo. ${errorMsg}`);
              formikHelpers.setSubmitting(false);
              return;
            }
          }

          if (selectedLogotype) {
            values.use_custom_logotype = true;

            const formData = new FormData();
            formData.append("file", selectedLogotype);
            setSelectedLogotype(null);
            const response = await fetch(
              "/api/admin/enterprise-settings/logo?is_logotype=true",
              {
                method: "PUT",
                body: formData,
              }
            );
            if (!response.ok) {
              const errorMsg = (await response.json()).detail;
              alert(`Failed to upload logo. ${errorMsg}`);
              formikHelpers.setSubmitting(false);
              return;
            }
          }

          formikHelpers.setValues(values);
          await updateEnterpriseSettings(values);
        }}
      >
        {({ isSubmitting, values, setValues }) => (
          <Form>
            <TextFormField
              label="Application Name"
              name="application_name"
              subtext={`The custom name you are giving Danswer for your organization. This will replace 'Danswer' everywhere in the UI.`}
              placeholder="Custom name which will replace 'Danswer'"
              disabled={isSubmitting}
            />

            <Label className="mt-4">Custom Logo</Label>

            {values.use_custom_logo ? (
              <div className="mt-3">
                <SubLabel>Current Custom Logo: </SubLabel>
                <img
                  src={"/api/enterprise-settings/logo?u=" + Date.now()}
                  alt="logo"
                  style={{ objectFit: "contain" }}
                  className="w-32 h-32 mb-10 mt-4"
                />

                <Button
                  variant="destructive"
                  size="sm"
                  type="button"
                  className="mb-8"
                  onClick={async () => {
                    const valuesWithoutLogo = {
                      ...values,
                      use_custom_logo: false,
                    };
                    await updateEnterpriseSettings(valuesWithoutLogo);
                    setValues(valuesWithoutLogo);
                  }}
                >
                  Delete
                </Button>

                <SubLabel>
                  Override the current custom logo by uploading a new image
                  below and clicking the Update button.
                </SubLabel>
              </div>
            ) : (
              <SubLabel>
                Specify your own logo to replace the standard Danswer logo.
              </SubLabel>
            )}

            <ImageUpload
              selectedFile={selectedLogo}
              setSelectedFile={setSelectedLogo}
            />

            <Separator />

            <AdvancedOptionsToggle
              showAdvancedOptions={showAdvancedOptions}
              setShowAdvancedOptions={setShowAdvancedOptions}
            />

            {showAdvancedOptions && (
              <div className="w-full flex flex-col gap-y-4">
                <Text>
                  Read{" "}
                  <Link
                    href={"https://docs.danswer.dev/enterprise_edition/theming"}
                    className="text-link cursor-pointer"
                  >
                    the docs
                  </Link>{" "}
                  to see whitelabelling examples in action.
                </Text>

                <TextFormField
                  label="Chat Header Content"
                  name="custom_header_content"
                  subtext={`Custom Markdown content that will be displayed as a banner at the top of the Chat page.`}
                  placeholder="Your header content..."
                  disabled={isSubmitting}
                />

                <BooleanFormField
                  name="two_lines_for_chat_header"
                  label="Two lines for chat header?"
                  subtext="If enabled, the chat header will be displayed on two lines instead of one."
                />

                <Separator />

                <TextFormField
                  label={
                    values.enable_consent_screen
                      ? "Consent Screen Header"
                      : "Popup Header"
                  }
                  name="custom_popup_header"
                  subtext={
                    values.enable_consent_screen
                      ? `The title for the consent screen that will be displayed for each user on their initial visit to the application. If left blank, title will default to "Terms of Use".`
                      : `The title for the popup that will be displayed for each user on their initial visit to the application. If left blank AND Custom Popup Content is specified, will use "Welcome to ${
                          values.application_name || "Danswer"
                        }!".`
                  }
                  placeholder={
                    values.enable_consent_screen
                      ? "Consent Screen Header"
                      : "Initial Popup Header"
                  }
                  disabled={isSubmitting}
                />

                <TextFormField
                  label={
                    values.enable_consent_screen
                      ? "Consent Screen Content"
                      : "Popup Content"
                  }
                  name="custom_popup_content"
                  subtext={
                    values.enable_consent_screen
                      ? `Custom Markdown content that will be displayed as a consent screen on initial visit to the application. If left blank, will default to "By clicking 'I Agree', you acknowledge that you agree to the terms of use of this application and consent to proceed."`
                      : `Custom Markdown content that will be displayed as a popup on initial visit to the application.`
                  }
                  placeholder={
                    values.enable_consent_screen
                      ? "Your consent screen content..."
                      : "Your popup content..."
                  }
                  isTextArea
                  disabled={isSubmitting}
                />

                <BooleanFormField
                  name="enable_consent_screen"
                  label="Enable Consent Screen"
                  subtext="If enabled, the initial popup will be transformed into a consent screen. Users will be required to agree to the terms before accessing the application on their first login."
                  disabled={isSubmitting}
                />

                <TextFormField
                  label="Chat Footer Text"
                  name="custom_lower_disclaimer_content"
                  subtext={`Custom Markdown content that will be displayed at the bottom of the Chat page.`}
                  placeholder="Your disclaimer content..."
                  isTextArea
                  disabled={isSubmitting}
                />

                <div>
                  <Label>Chat Footer Logotype</Label>

                  {values.use_custom_logotype ? (
                    <div className="mt-3">
                      <SubLabel>Current Custom Logotype: </SubLabel>
                      <img
                        src={
                          "/api/enterprise-settings/logotype?u=" + Date.now()
                        }
                        alt="logotype"
                        style={{ objectFit: "contain" }}
                        className="w-32 h-32 mb-10 mt-4"
                      />

                      <Button
                        variant="destructive"
                        size="sm"
                        type="button"
                        className="mb-8"
                        onClick={async () => {
                          const valuesWithoutLogotype = {
                            ...values,
                            use_custom_logotype: false,
                          };
                          await updateEnterpriseSettings(valuesWithoutLogotype);
                          setValues(valuesWithoutLogotype);
                        }}
                      >
                        Delete
                      </Button>

                      <SubLabel>
                        Override your uploaded custom logotype by uploading a
                        new image below and clicking the Update button. This
                        logotype is the text-based logo that will be rendered at
                        the bottom right of the chat screen.
                      </SubLabel>
                    </div>
                  ) : (
                    <SubLabel>
                      Add a custom logotype by uploading a new image below and
                      clicking the Update button. This logotype is the
                      text-based logo that will be rendered at the bottom right
                      of the chat screen.
                    </SubLabel>
                  )}
                  <ImageUpload
                    selectedFile={selectedLogotype}
                    setSelectedFile={setSelectedLogotype}
                  />
                </div>
              </div>
            )}

            <Button type="submit" className="mt-4">
              Update
            </Button>
          </Form>
        )}
      </Formik>
    </div>
  );
}
