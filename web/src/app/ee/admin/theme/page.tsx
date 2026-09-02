"use client";

import { useAdminRouteTitle } from "@/lib/adminNavLabels";
import { useTranslations } from "next-intl";
import { SettingsLayouts, toast } from "@opal/layouts";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { Button } from "@opal/components";
import {
  AppearanceThemeSettings,
  AppearanceThemeSettingsRef,
} from "./AppearanceThemeSettings";
import { useRef, useState } from "react";
import { useSettings } from "@/lib/settings/hooks";
import { Formik, Form } from "formik";
import * as Yup from "yup";
import { EnterpriseSettings } from "@/lib/settings/types";
import useSWR, { mutate } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { AdminBanner } from "@/lib/banner/interfaces";
import { invalidateNotificationCaches } from "@/lib/notifications/api";

const route = ADMIN_ROUTES.THEME;

const CHAR_LIMITS = {
  application_name: 50,
  custom_greeting_message: 50,
  custom_login_subtitle: 100,
  custom_header_content: 100,
  custom_lower_disclaimer_content: 200,
  custom_popup_header: 100,
  custom_popup_content: 500,
  consent_screen_prompt: 200,
  system_announcement_header: 100,
  system_announcement_content: 1000,
};

export default function ThemePage() {
  const t = useTranslations("admin.theme");
  const adminRouteTitle = useAdminRouteTitle();
  const settings = useSettings();
  const enterpriseSettings = settings.enterprise;
  const [selectedLogo, setSelectedLogo] = useState<File | null>(null);
  const [logoVersion, setLogoVersion] = useState(0);
  const appearanceSettingsRef = useRef<AppearanceThemeSettingsRef>(null);
  // The banner seeds Formik initialValues once, so the form renders only after
  // this fetch settles (a failed fetch counts as "no banner"). Background
  // revalidation stays off, and only our own post-save mutate refreshes it.
  const { data: adminBanner, error: adminBannerError } =
    useSWR<AdminBanner | null>(SWR_KEYS.adminBanner, errorHandlingFetcher, {
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
    });
  const bannerLoaded = adminBanner !== undefined || Boolean(adminBannerError);
  const currentBanner = adminBanner ?? null;

  async function updateEnterpriseSettings(
    newValues: EnterpriseSettings
  ): Promise<boolean> {
    const response = await fetch("/api/admin/enterprise-settings", {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        ...enterpriseSettings,
        ...newValues,
      }),
    });
    if (response.ok) {
      await mutate(SWR_KEYS.enterpriseSettings);
      return true;
    } else {
      const errorMsg = (await response.json()).detail;
      alert(t("page.settingsSaveFailed.message", { error: errorMsg }));
      return false;
    }
  }

  async function mutateAdminBanner(
    init: RequestInit,
    failMessage: string
  ): Promise<boolean> {
    const response = await fetch("/api/admin/banner", init);
    if (!response.ok) {
      const errorMsg = (await response.json()).detail;
      toast.error(`${failMessage} ${errorMsg}`);
      return false;
    }
    await mutate(SWR_KEYS.adminBanner);
    // The banner reaches users as a synthesized notification, so the mounted
    // banner queue and bell must refetch to show the change without a reload.
    await invalidateNotificationCaches();
    return true;
  }

  const maxCharsMessage = (count: number) =>
    t("page.validation.maxChars", { count });

  const validationSchema = Yup.object().shape({
    application_name: Yup.string()
      .trim()
      .max(
        CHAR_LIMITS.application_name,
        maxCharsMessage(CHAR_LIMITS.application_name)
      )
      .nullable(),
    logo_display_style: Yup.string()
      .oneOf(["logo_and_name", "logo_only", "name_only"])
      .required(),
    use_custom_logo: Yup.boolean().required(),
    custom_greeting_message: Yup.string()
      .max(
        CHAR_LIMITS.custom_greeting_message,
        maxCharsMessage(CHAR_LIMITS.custom_greeting_message)
      )
      .nullable(),
    custom_login_subtitle: Yup.string()
      .max(
        CHAR_LIMITS.custom_login_subtitle,
        maxCharsMessage(CHAR_LIMITS.custom_login_subtitle)
      )
      .nullable(),
    custom_header_content: Yup.string()
      .max(
        CHAR_LIMITS.custom_header_content,
        maxCharsMessage(CHAR_LIMITS.custom_header_content)
      )
      .nullable(),
    custom_lower_disclaimer_content: Yup.string()
      .max(
        CHAR_LIMITS.custom_lower_disclaimer_content,
        maxCharsMessage(CHAR_LIMITS.custom_lower_disclaimer_content)
      )
      .nullable(),
    show_first_visit_notice: Yup.boolean().nullable(),
    custom_popup_header: Yup.string()
      .max(
        CHAR_LIMITS.custom_popup_header,
        maxCharsMessage(CHAR_LIMITS.custom_popup_header)
      )
      .when("show_first_visit_notice", {
        is: true,
        then: (schema) =>
          schema.required(t("page.validation.noticeHeaderRequired")),
        otherwise: (schema) => schema.nullable(),
      }),
    custom_popup_content: Yup.string()
      .max(
        CHAR_LIMITS.custom_popup_content,
        maxCharsMessage(CHAR_LIMITS.custom_popup_content)
      )
      .when("show_first_visit_notice", {
        is: true,
        then: (schema) =>
          schema.required(t("page.validation.noticeContentRequired")),
        otherwise: (schema) => schema.nullable(),
      }),
    enable_consent_screen: Yup.boolean().nullable(),
    consent_screen_prompt: Yup.string()
      .max(
        CHAR_LIMITS.consent_screen_prompt,
        maxCharsMessage(CHAR_LIMITS.consent_screen_prompt)
      )
      .when("enable_consent_screen", {
        is: true,
        then: (schema) =>
          schema.required(t("page.validation.consentPromptRequired")),
        otherwise: (schema) => schema.nullable(),
      }),
    custom_help_link_label: Yup.string().nullable(),
    custom_help_link_url: Yup.string()
      .nullable()
      .when("custom_help_link_label", {
        is: (label: string | null | undefined) =>
          typeof label === "string" && label.trim().length > 0,
        then: (schema) =>
          schema
            .required(t("page.validation.urlRequiredWithLabel"))
            .url(t("page.validation.invalidUrl")),
        otherwise: (schema) =>
          schema.test(
            "optional-url",
            t("page.validation.invalidUrl"),
            (value) =>
              value == null ||
              value === "" ||
              Yup.string().url().isValidSync(value)
          ),
      }),
    hide_onyx_branding: Yup.boolean().nullable(),
    system_announcement_enabled: Yup.boolean().nullable(),
    system_announcement_header: Yup.string()
      .trim()
      .max(
        CHAR_LIMITS.system_announcement_header,
        maxCharsMessage(CHAR_LIMITS.system_announcement_header)
      )
      .when("system_announcement_enabled", {
        is: true,
        then: (schema) =>
          schema.required(t("page.validation.noticeHeaderRequired")),
        otherwise: (schema) => schema.nullable(),
      }),
    system_announcement_content: Yup.string()
      .trim()
      .max(
        CHAR_LIMITS.system_announcement_content,
        maxCharsMessage(CHAR_LIMITS.system_announcement_content)
      )
      .when("system_announcement_enabled", {
        is: true,
        then: (schema) =>
          schema.required(t("page.validation.noticeContentRequired")),
        otherwise: (schema) => schema.nullable(),
      }),
    system_announcement_show_as_popup: Yup.boolean().nullable(),
  });

  if (!bannerLoaded) return null;

  return (
    <Formik
      initialValues={{
        application_name: enterpriseSettings?.application_name || "",
        logo_display_style:
          enterpriseSettings?.logo_display_style || "logo_and_name",
        use_custom_logo: enterpriseSettings?.use_custom_logo || false,
        custom_greeting_message:
          enterpriseSettings?.custom_greeting_message || "",
        custom_login_subtitle: enterpriseSettings?.custom_login_subtitle || "",
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
        custom_help_link_url: enterpriseSettings?.custom_help_link_url || "",
        custom_help_link_label:
          enterpriseSettings?.custom_help_link_label || "",
        hide_onyx_branding: enterpriseSettings?.hide_onyx_branding || false,
        system_announcement_enabled: !!currentBanner,
        system_announcement_header: currentBanner?.title || "",
        system_announcement_content: currentBanner?.content || "",
        system_announcement_show_as_popup:
          currentBanner?.show_as_popup || false,
      }}
      validationSchema={validationSchema}
      validateOnChange={false}
      onSubmit={async (values, formikHelpers) => {
        let logoUploaded = false;

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
            alert(t("page.logoUploadFailed.message", { error: errorMsg }));
            formikHelpers.setSubmitting(false);
            return;
          }
          // Only clear the selected logo after a successful upload
          setSelectedLogo(null);
          logoUploaded = true;
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
          custom_login_subtitle: values.custom_login_subtitle?.trim() || null,
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
          custom_help_link_url: values.custom_help_link_url?.trim() || null,
          custom_help_link_label: values.custom_help_link_label?.trim() || null,
          hide_onyx_branding: values.hide_onyx_branding ?? null,
        });

        // Only touch the banner after the settings save succeeds, and only when
        // its own fields changed, so an unrelated edit does not re-publish it.
        const trimmedHeader = values.system_announcement_header.trim();
        const trimmedContent =
          values.system_announcement_content.trim() || null;
        const bannerChanged =
          values.system_announcement_enabled !== !!currentBanner ||
          trimmedHeader !== (currentBanner?.title ?? "") ||
          trimmedContent !== (currentBanner?.content ?? null) ||
          values.system_announcement_show_as_popup !==
            (currentBanner?.show_as_popup ?? false);

        let bannerOk = true;
        if (success && bannerChanged) {
          if (values.system_announcement_enabled) {
            bannerOk = await mutateAdminBanner(
              {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  title: trimmedHeader,
                  content: trimmedContent,
                  show_as_popup: values.system_announcement_show_as_popup,
                }),
              },
              t("page.announcementSaveFailed.message")
            );
          } else if (currentBanner) {
            bannerOk = await mutateAdminBanner(
              { method: "DELETE" },
              t("page.announcementClearFailed.message")
            );
          }
        }

        // After a successful save, reset Formik's baseline so dirty comparisons
        // reflect the newly-saved values.
        if (success && bannerOk) {
          formikHelpers.resetForm({ values });
          if (logoUploaded) {
            setLogoVersion((v) => v + 1);
          }
          toast.success(t("page.saveSuccess.message"));
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
            <SettingsLayouts.Root>
              <SettingsLayouts.Header
                title={adminRouteTitle(route)}
                description={t("page.description")}
                icon={route.icon}
                rightChildren={
                  <Button
                    disabled={isSubmitting || (!dirty && !hasLogoChange)}
                    type="button"
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
                    {isSubmitting
                      ? t("page.applying.label")
                      : t("page.applyButton.label")}
                  </Button>
                }
              />
              <SettingsLayouts.Body>
                <AppearanceThemeSettings
                  ref={appearanceSettingsRef}
                  selectedLogo={selectedLogo}
                  setSelectedLogo={setSelectedLogo}
                  logoVersion={logoVersion}
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
