"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Formik, Form } from "formik";
import * as Yup from "yup";
import { useSWRConfig } from "swr";
import {
  ConfirmationModalLayout,
  InputHorizontal,
  InputVertical,
  Section,
  toast,
} from "@opal/layouts";
import { SvgLock, SvgTrash } from "@opal/icons";
import {
  Button,
  InputPasswordTypeIn,
  InputTypeIn,
  Text,
  useCreateModal,
} from "@opal/components";
import { useUser } from "@/providers/UserProvider";
import useUserPersonalization from "@/hooks/useUserPersonalization";
import useChatSessions from "@/hooks/useChatSessions";
import { deleteAllChatSessions } from "@/app/app/services/lib";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { ErrorResponseBody } from "@/lib/fetcher";
import SettingsSection from "@/views/settings/SettingsSection";

export default function AccountSettings() {
  const t = useTranslations("settings");
  const { user, authTypeMetadata, updateUserPersonalization } = useUser();
  const { mutate } = useSWRConfig();
  const { refreshChatSessions } = useChatSessions();
  const [isDeleting, setIsDeleting] = useState(false);
  const deleteAllChatsModal = useCreateModal();
  const passwordModal = useCreateModal();

  const {
    personalizationValues,
    updatePersonalizationField,
    handleSavePersonalization,
  } = useUserPersonalization(user, updateUserPersonalization, {
    onError: () => toast.error(t("profile.toasts.updateFailed")),
  });

  // Track initial values to detect changes
  const initialNameRef = useRef(personalizationValues.name);
  const initialRoleRef = useRef(personalizationValues.role);

  // Update refs when personalization values change from external source
  useEffect(() => {
    initialNameRef.current = personalizationValues.name;
    initialRoleRef.current = personalizationValues.role;
  }, [user?.personalization]);

  // TODO(auth-refresh): only passwordMinLength is enforced here; the remaining
  // constraints (max length, uppercase, lowercase, digit, special char) will be
  // wired up when this form is refreshed as part of auth-refresh.
  const passwordValidationSchema = Yup.object().shape({
    currentPassword: Yup.string().required(
      t("accounts.passwordModal.validation.currentRequired")
    ),
    newPassword: Yup.string()
      .min(
        authTypeMetadata?.passwordMinLength ?? 0,
        t("accounts.passwordModal.validation.minLength", {
          min: authTypeMetadata?.passwordMinLength ?? 0,
        })
      )
      .required(t("accounts.passwordModal.validation.newRequired")),
    confirmPassword: Yup.string()
      .oneOf(
        [Yup.ref("newPassword")],
        t("accounts.passwordModal.validation.mismatch")
      )
      .required(t("accounts.passwordModal.validation.confirmRequired")),
  });

  const handleDeleteAllChats = useCallback(async () => {
    setIsDeleting(true);
    try {
      const response = await deleteAllChatSessions();
      if (response.ok) {
        await refreshChatSessions();
        deleteAllChatsModal.toggle(false);
      } else {
        throw new Error("Failed to delete all chat sessions");
      }
    } catch (error) {
      toast.error(t("dangerZone.deleteAllChats.toasts.deleteFailed"));
    } finally {
      setIsDeleting(false);
    }
  }, [refreshChatSessions, deleteAllChatsModal.toggle, t]);

  const handleChangePassword = useCallback(
    async (values: {
      currentPassword: string;
      newPassword: string;
      confirmPassword: string;
    }) => {
      try {
        const response = await fetch("/api/password/change-password", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            old_password: values.currentPassword,
            new_password: values.newPassword,
          }),
        });

        if (response.ok) {
          passwordModal.toggle(false);
          // The server revoked every token. Clear the cached list first so
          // a failed refetch cannot show revoked tokens.
          await mutate(SWR_KEYS.userPats, [], { revalidate: true });
        } else {
          const errorData: ErrorResponseBody = await response.json();
          toast.error(
            errorData.detail || t("accounts.passwordModal.toasts.updateFailed")
          );
        }
      } catch (error) {
        toast.error(t("accounts.passwordModal.toasts.networkError"));
      }
    },
    [mutate, passwordModal.toggle, t]
  );

  return (
    <>
      <deleteAllChatsModal.Provider>
        <ConfirmationModalLayout
          icon={SvgTrash}
          title={t("dangerZone.deleteAllChats.confirm.title")}
          onClose={() => deleteAllChatsModal.toggle(false)}
          submit={
            <Button
              disabled={isDeleting}
              variant="danger"
              onClick={() => {
                void handleDeleteAllChats();
              }}
            >
              {isDeleting
                ? t("dangerZone.deleteAllChats.confirm.deleting")
                : t("dangerZone.deleteAllChats.confirm.submit")}
            </Button>
          }
        >
          <Section gap={2} alignItems="start">
            <Text as="p" font="main-ui-body" color="text-05">
              {t("dangerZone.deleteAllChats.confirm.description")}
            </Text>
            <Text as="p" font="main-ui-body" color="text-05">
              {t("dangerZone.deleteAllChats.confirm.question")}
            </Text>
          </Section>
        </ConfirmationModalLayout>
      </deleteAllChatsModal.Provider>

      <passwordModal.Provider>
        <Formik
          initialValues={{
            currentPassword: "",
            newPassword: "",
            confirmPassword: "",
          }}
          validationSchema={passwordValidationSchema}
          validateOnChange={true}
          validateOnBlur={true}
          onSubmit={() => undefined}
        >
          {({
            values,
            handleChange,
            handleBlur,
            isSubmitting,
            dirty,
            isValid,
            errors,
            touched,
            setSubmitting,
          }) => (
            <Form>
              <ConfirmationModalLayout
                icon={SvgLock}
                title={t("accounts.passwordModal.title")}
                description={t("accounts.passwordModal.description")}
                submit={
                  <Button
                    disabled={isSubmitting || !dirty || !isValid}
                    onClick={async () => {
                      setSubmitting(true);
                      try {
                        await handleChangePassword(values);
                      } finally {
                        setSubmitting(false);
                      }
                    }}
                  >
                    {isSubmitting
                      ? t("accounts.passwordModal.submit.updating")
                      : t("accounts.passwordModal.submit.update")}
                  </Button>
                }
                onClose={() => {
                  passwordModal.toggle(false);
                }}
              >
                <Section gap={4}>
                  <Section gap={1} alignItems="start">
                    <InputVertical
                      withLabel="currentPassword"
                      title={t("accounts.passwordModal.currentPassword.title")}
                    >
                      <InputPasswordTypeIn
                        name="currentPassword"
                        value={values.currentPassword}
                        onChange={handleChange}
                        onBlur={handleBlur}
                        error={
                          touched.currentPassword && !!errors.currentPassword
                        }
                      />
                    </InputVertical>
                  </Section>
                  <Section gap={1} alignItems="start">
                    <InputVertical
                      withLabel="newPassword"
                      title={t("accounts.passwordModal.newPassword.title")}
                    >
                      <InputPasswordTypeIn
                        name="newPassword"
                        value={values.newPassword}
                        onChange={handleChange}
                        onBlur={handleBlur}
                        error={touched.newPassword && !!errors.newPassword}
                      />
                    </InputVertical>
                  </Section>
                  <Section gap={1} alignItems="start">
                    <InputVertical
                      withLabel="confirmPassword"
                      title={t("accounts.passwordModal.confirmPassword.title")}
                    >
                      <InputPasswordTypeIn
                        name="confirmPassword"
                        value={values.confirmPassword}
                        onChange={handleChange}
                        onBlur={handleBlur}
                        error={
                          touched.confirmPassword && !!errors.confirmPassword
                        }
                      />
                    </InputVertical>
                  </Section>
                </Section>
              </ConfirmationModalLayout>
            </Form>
          )}
        </Formik>
      </passwordModal.Provider>

      <Section gap={8}>
        <SettingsSection title={t("profile.title")}>
          <InputHorizontal
            title={t("profile.fullName.title")}
            description={t("profile.fullName.description")}
            center
            withLabel
            fillInput
            responsive
          >
            <InputTypeIn
              placeholder={t("profile.fullName.placeholder")}
              value={personalizationValues.name}
              onChange={(e) =>
                updatePersonalizationField("name", e.target.value)
              }
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.currentTarget.blur();
                }
              }}
              onBlur={() => {
                // Only save if the value has changed
                if (personalizationValues.name !== initialNameRef.current) {
                  void handleSavePersonalization({
                    name: personalizationValues.name,
                  });
                  initialNameRef.current = personalizationValues.name;
                }
              }}
            />
          </InputHorizontal>
          <InputHorizontal
            title={t("profile.workRole.title")}
            description={t("profile.workRole.description")}
            center
            withLabel
            fillInput
            responsive
          >
            <InputTypeIn
              placeholder={t("profile.workRole.placeholder")}
              value={personalizationValues.role}
              onChange={(e) =>
                updatePersonalizationField("role", e.target.value)
              }
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.currentTarget.blur();
                }
              }}
              onBlur={() => {
                // Only save if the value has changed
                if (personalizationValues.role !== initialRoleRef.current) {
                  void handleSavePersonalization({
                    role: personalizationValues.role,
                  });
                  initialRoleRef.current = personalizationValues.role;
                }
              }}
            />
          </InputHorizontal>
          {user?.password_configured && (
            <InputHorizontal
              title={t("accounts.password.title")}
              description={t("accounts.password.description")}
              center
            >
              <Button
                prominence="secondary"
                icon={SvgLock}
                onClick={() => passwordModal.toggle(true)}
                interaction={passwordModal.isOpen ? "hover" : "rest"}
              >
                {t("accounts.password.changeButton")}
              </Button>
            </InputHorizontal>
          )}
        </SettingsSection>

        <SettingsSection title={t("dangerZone.title")}>
          <InputHorizontal
            title={t("dangerZone.deleteAllChats.title")}
            description={t("dangerZone.deleteAllChats.description")}
            center
          >
            <Button
              variant="danger"
              prominence="secondary"
              onClick={() => deleteAllChatsModal.toggle(true)}
              icon={SvgTrash}
              interaction={deleteAllChatsModal.isOpen ? "hover" : "rest"}
            >
              {t("dangerZone.deleteAllChats.button")}
            </Button>
          </InputHorizontal>
        </SettingsSection>
      </Section>
    </>
  );
}
