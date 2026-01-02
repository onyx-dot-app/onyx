"use client";

import * as SettingsLayouts from "@/layouts/settings-layouts";
import { SvgPaintBrush } from "@opal/icons";
import Button from "@/refresh-components/buttons/Button";
import {
  AppearanceThemeSettings,
  AppearanceThemeSettingsRef,
} from "./AppearanceThemeSettings";
import { useContext, useRef, useState } from "react";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { usePopup } from "@/components/admin/connectors/Popup";
import { Formik, Form } from "formik";
import * as Yup from "yup";
import { EnterpriseSettings } from "@/app/admin/settings/interfaces";
import { useRouter } from "next/navigation";

const CHAR_LIMITS = {
  application_name: 50,
  custom_greeting_message: 50,
  custom_header_content: 100,
  custom_lower_disclaimer_content: 200,
  custom_popup_header: 100,
  custom_popup_content: 500,
  consent_screen_prompt: 200,
};

export default function ThemePage() {
  const router = useRouter();
  const settings = useContext(SettingsContext);
  const [selectedLogo, setSelectedLogo] = useState<File | null>(null);
  const appearanceSettingsRef = useRef<AppearanceThemeSettingsRef>(null);
  const { popup, setPopup } = usePopup();

  if (!settings) {
    return null;
  }

  const enterpriseSettings = settings.enterpriseSettings;

  async function updateEnterpriseSettings(
    newValues: EnterpriseSettings
  ): Promise<boolean> {
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
      return true;
    } else {
      const errorMsg = (await response.json()).detail;
      alert(`Failed to update settings. ${errorMsg}`);
      return false;
    }
  }

  const validationSchema = Yup.object().shape({
    application_name: Yup.string()
      .trim()
      .max(
        CHAR_LIMITS.application_name,
        `Maximum ${CHAR_LIMITS.application_name} characters`
      )
      .nullable(),
    logo_display_style: Yup.string()
      .oneOf(["logo_and_name", "logo_only", "name_only"])
      .required(),
    use_custom_logo: Yup.boolean().required(),
    custom_greeting_message: Yup.string()
      .max(
        CHAR_LIMITS.custom_greeting_message,
        `Maximum ${CHAR_LIMITS.custom_greeting_message} characters`
      )
      .nullable(),
    custom_header_content: Yup.string()
      .max(
        CHAR_LIMITS.custom_header_content,
        `Maximum ${CHAR_LIMITS.custom_header_content} characters`
      )
      .nullable(),
    custom_lower_disclaimer_content: Yup.string()
      .max(
        CHAR_LIMITS.custom_lower_disclaimer_content,
        `Maximum ${CHAR_LIMITS.custom_lower_disclaimer_content} characters`
      )
      .nullable(),
    show_first_visit_notice: Yup.boolean().nullable(),
    custom_popup_header: Yup.string()
      .max(
        CHAR_LIMITS.custom_popup_header,
        `Maximum ${CHAR_LIMITS.custom_popup_header} characters`
      )
      .when("show_first_visit_notice", {
        is: true,
        then: (schema) => schema.required("Notice Header is required"),
        otherwise: (schema) => schema.nullable(),
      }),
    custom_popup_content: Yup.string()
      .max(
        CHAR_LIMITS.custom_popup_content,
        `Maximum ${CHAR_LIMITS.custom_popup_content} characters`
      )
      .when("show_first_visit_notice", {
        is: true,
        then: (schema) => schema.required("Notice Content is required"),
        otherwise: (schema) => schema.nullable(),
      }),
    enable_consent_screen: Yup.boolean().nullable(),
    consent_screen_prompt: Yup.string()
      .max(
        CHAR_LIMITS.consent_screen_prompt,
        `Maximum ${CHAR_LIMITS.consent_screen_prompt} characters`
      )
      .when("enable_consent_screen", {
        is: true,
        then: (schema) => schema.required("Notice Consent Prompt is required"),
        otherwise: (schema) => schema.nullable(),
      }),
  });

  return (
    <Formik
      initialValues={{
        application_name: enterpriseSettings?.application_name || "",
        logo_display_style:
          enterpriseSettings?.logo_display_style || "logo_and_name",
        use_custom_logo: enterpriseSettings?.use_custom_logo || false,
        custom_greeting_message:
          enterpriseSettings?.custom_greeting_message || "",
        custom_header_content: enterpriseSettings?.custom_header_content || "",
        custom_lower_disclaimer_content:
          enterpriseSettings?.custom_lower_disclaimer_content || "",
        show_first_visit_notice:
          enterpriseSettings?.show_first_visit_notice || false,
        custom_popup_header: enterpriseSettings?.custom_popup_header || "",
        custom_popup_content: enterpriseSettings?.custom_popup_content || "",
        enable_consent_screen:
          enterpriseSettings?.enable_consent_screen || false,
        consent_screen_prompt: enterpriseSettings?.consent_screen_prompt || "",
      }}
      validationSchema={validationSchema}
      validateOnChange={false}
      onSubmit={async (values, formikHelpers) => {
        // Handle logo upload if a new logo was selected
        if (selectedLogo) {
          const formData = new FormData();
          formData.append("file", selectedLogo);
          const response = await fetch("/api/admin/enterprise-settings/logo", {
            method: "PUT",
            body: formData,
          });
          if (!response.ok) {
            const errorMsg = (await response.json()).detail;
            alert(`Failed to upload logo. ${errorMsg}`);
            formikHelpers.setSubmitting(false);
            return;
          }
          // Only clear the selected logo after a successful upload
          setSelectedLogo(null);
          values.use_custom_logo = true;
        }

        // Update enterprise settings
        const success = await updateEnterpriseSettings({
          application_name: values.application_name || null,
          use_custom_logo: values.use_custom_logo,
          use_custom_logotype: enterpriseSettings?.use_custom_logotype || false,
          logo_display_style: values.logo_display_style || null,
          custom_nav_items: enterpriseSettings?.custom_nav_items || [],
          custom_greeting_message: values.custom_greeting_message || null,
          custom_header_content: values.custom_header_content || null,
          custom_lower_disclaimer_content:
            values.custom_lower_disclaimer_content || null,
          two_lines_for_chat_header:
            enterpriseSettings?.two_lines_for_chat_header || null,
          custom_popup_header: values.custom_popup_header || null,
          custom_popup_content: values.custom_popup_content || null,
          show_first_visit_notice: values.show_first_visit_notice || null,
          enable_consent_screen: values.enable_consent_screen || null,
          consent_screen_prompt: values.consent_screen_prompt || null,
        });

        // Important: after a successful save, reset Formik's "baseline" so
        // dirty comparisons reflect the newly-saved values.
        if (success) {
          formikHelpers.resetForm({ values });
          setPopup({
            type: "success",
            message: "Appearance settings saved successfully!",
          });
        }

        formikHelpers.setSubmitting(false);
      }}
    >
      {({
        isSubmitting,
        dirty,
        values,
        validateForm,
        setErrors,
        setTouched,
        submitForm,
      }) => {
        const hasLogoChange = !!selectedLogo;

        return (
          <Form className="w-full h-full">
            {popup}
            <SettingsLayouts.Root>
              <SettingsLayouts.Header
                title="Appearance & Theming"
                description="Customize how the application appears to users across your organization."
                icon={SvgPaintBrush}
                rightChildren={
                  <Button
                    type="button"
                    disabled={isSubmitting || (!dirty && !hasLogoChange)}
                    onClick={async () => {
                      const errors = await validateForm();
                      if (Object.keys(errors).length > 0) {
                        setErrors(errors);
                        appearanceSettingsRef.current?.focusFirstError(errors);
                        return;
                      }
                      await submitForm();
                    }}
                  >
                    {isSubmitting ? "Applying..." : "Apply Changes"}
                  </Button>
                }
              />
              <SettingsLayouts.Body>
                <AppearanceThemeSettings
                  ref={appearanceSettingsRef}
                  selectedLogo={selectedLogo}
                  setSelectedLogo={setSelectedLogo}
                  charLimits={CHAR_LIMITS}
                />
              </SettingsLayouts.Body>
            </SettingsLayouts.Root>
          </Form>
        );
      }}
    </Formik>
  );
}
