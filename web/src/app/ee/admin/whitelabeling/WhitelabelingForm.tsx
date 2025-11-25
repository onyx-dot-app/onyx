"use client";
import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../../../i18n/keys";

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
  const { t } = useTranslation();
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
    const response = await fetch("/api/admin/settings", {
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
          auto_scroll: settings?.settings?.auto_scroll || false,
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
          auto_scroll: Yup.boolean().nullable(),
          application_name: Yup.string()
            .trim()
            .min(1, t(k.APP_NAME_CANNOT_BE_EMPTY))
            .nullable(),
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
              "/api/admin/settings/logo",
              {
                method: "PUT",
                body: formData,
              }
            );
            if (!response.ok) {
              const errorMsg = (await response.json()).detail;
              alert(`${t(k.FAILED_TO_UPLOAD_LOGO)} ${errorMsg}`);
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
              "/api/admin/settings/logo?is_logotype=true",
              {
                method: "PUT",
                body: formData,
              }
            );
            if (!response.ok) {
              const errorMsg = (await response.json()).detail;
              alert(`${t(k.FAILED_TO_UPLOAD_LOGO)} ${errorMsg}`);
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
              label={t(k.APP_NAME_LABEL)}
              name="application_name"
              subtext={`${t(k.THE_CUSTOM_NAME_YOU_ARE_GIVING)}`}
              placeholder={t(k.APP_NAME_PLACEHOLDER)}
              disabled={isSubmitting}
            />

            <Label className="mt-4">{t(k.CUSTOM_LOGO)}</Label>

            {values.use_custom_logo ? (
              <div className="mt-3">
                <SubLabel>{t(k.CURRENT_CUSTOM_LOGO)}</SubLabel>
                <img
                  src={"/api/settings/logo?u=" + Date.now()}
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
                  {t(k.DELETE)}
                </Button>

                <SubLabel>{t(k.OVERRIDE_THE_CURRENT_CUSTOM_LO)}</SubLabel>
              </div>
            ) : (
              <SubLabel>{t(k.SPECIFY_YOUR_OWN_LOGO_TO_REPLA)}</SubLabel>
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
                  {t(k.READ)}{" "}
                  <Link
                    href={"https://docs.onyx.app/enterprise_edition/theming"}
                    className="text-link cursor-pointer"
                  >
                    {t(k.THE_DOCS)}
                  </Link>{" "}
                  {t(k.TO_SEE_WHITELABELING_EXAMPLES)}
                </Text>

                <TextFormField
                  label="Chat Header Content"
                  name="custom_header_content"
                  subtext={`${t(k.CUSTOM_MARKDOWN_CONTENT_THAT_W)}`}
                  placeholder={t(k.HEADER_CONTENT_PLACEHOLDER)}
                  disabled={isSubmitting}
                />

                <BooleanFormField
                  name="two_lines_for_chat_header"
                  label={t(k.TWO_LINE_HEADER_LABEL)}
                  subtext={t(k.TWO_LINE_HEADER_SUBTEXT)}
                />

                <Separator />

                <TextFormField
                  label={
                    values.enable_consent_screen
                      ? t(k.CONSENT_SCREEN_HEADER)
                      : t(k.POPUP_HEADER)
                  }
                  name="custom_popup_header"
                  subtext={
                    values.enable_consent_screen
                      ? `${t(k.THE_TITLE_FOR_THE_CONSENT_SCRE)}`
                      : `${t(k.THE_TITLE_FOR_THE_POPUP_THAT_W)} ${
                          values.application_name || t(k.ONYX)
                        }${t(k._18)}`
                  }
                  placeholder={
                    values.enable_consent_screen
                      ? t(k.CONSENT_SCREEN_HEADER)
                      : t(k.INITIAL_POPUP_HEADER)
                  }
                  disabled={isSubmitting}
                />

                <TextFormField
                  label={
                    values.enable_consent_screen
                      ? t(k.CONSENT_SCREEN_CONTENT)
                      : t(k.POPUP_CONTENT)
                  }
                  name="custom_popup_content"
                  subtext={
                    values.enable_consent_screen
                      ? `${t(k.CUSTOM_MARKDOWN_CONTENT_THAT_W1)}`
                      : `${t(k.CUSTOM_MARKDOWN_CONTENT_THAT_W2)}`
                  }
                  placeholder={
                    values.enable_consent_screen
                      ? t(k.YOUR_CONSENT_SCREEN_CONTENT)
                      : t(k.YOUR_POPUP_CONTENT)
                  }
                  isTextArea
                  disabled={isSubmitting}
                />

                <BooleanFormField
                  name="enable_consent_screen"
                  label={t(k.ENABLE_CONSENT_SCREEN_LABEL)}
                  subtext={t(k.ENABLE_CONSENT_SCREEN_SUBTEXT)}
                  disabled={isSubmitting}
                />

                <TextFormField
                  label={t(k.CHAT_FOOTER_TEXT_LABEL)}
                  name="custom_lower_disclaimer_content"
                  subtext={`${t(k.CUSTOM_MARKDOWN_CONTENT_THAT_W3)}`}
                  placeholder={t(k.DISCLAIMER_CONTENT_PLACEHOLDER)}
                  isTextArea
                  disabled={isSubmitting}
                />

                <div>
                  <Label>{t(k.CHAT_FOOTER_LOGOTYPE)}</Label>

                  {values.use_custom_logotype ? (
                    <div className="mt-3">
                      <SubLabel>{t(k.CURRENT_CUSTOM_LOGOTYPE)}</SubLabel>
                      <img
                        src={
                          "/api/settings/logotype?u=" + Date.now()
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
                        {t(k.DELETE)}
                      </Button>

                      <SubLabel>{t(k.OVERRIDE_YOUR_UPLOADED_CUSTOM)}</SubLabel>
                    </div>
                  ) : (
                    <SubLabel>{t(k.ADD_A_CUSTOM_LOGOTYPE_BY_UPLOA)}</SubLabel>
                  )}
                  <ImageUpload
                    selectedFile={selectedLogotype}
                    setSelectedFile={setSelectedLogotype}
                  />
                </div>
              </div>
            )}

            <Button type="submit" className="mt-4">
              {t(k.UPDATE)}
            </Button>
          </Form>
        )}
      </Formik>
    </div>
  );
}
