"use client";

import { useCallback, useState } from "react";
import dynamic from "next/dynamic";
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
import { SvgImage, SvgLock, SvgTrash } from "@opal/icons";
import {
  AvatarButton,
  Button,
  CopyButton,
  Dropdown,
  InputPasswordTypeIn,
  InputSingleSelect,
  InputTypeIn,
  Text,
  useCreateModal,
} from "@opal/components";
import { useImageDropzone } from "@opal/hooks";
import { useUser } from "@/providers/UserProvider";
import { useSettings } from "@/lib/settings/hooks";
import {
  buildUserProfileImageUrl,
  getUserAddressedName,
  getUserEmail,
} from "@/lib/users/svc";
import UserAvatar from "@/refresh-components/avatars/UserAvatar";
import { WORK_ROLE_OPTIONS, WORK_ROLE_VALUES } from "@/lib/users/workRoles";
import useUserPersonalization from "@/hooks/useUserPersonalization";
import useChatSessions from "@/hooks/useChatSessions";
import { useUnseenRuns } from "@/lib/chat/runStatus";
import { deleteAllChatSessions } from "@/app/app/services/lib";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { ErrorResponseBody } from "@/lib/fetcher";
import SettingsSection from "@/views/settings/SettingsSection";

// Select value for "Other". It is never stored: the free-text role is.
const OTHER_WORK_ROLE = "__other__";

// Loaded on first use: it bundles the cropper.
const ProfilePhotoCropModal = dynamic(
  () => import("@/views/settings/ProfilePhotoCropModal"),
  { ssr: false }
);

const PROFILE_PHOTO_SIZE_PX = 40;
const PROFILE_IMAGE_API = "/api/user/profile-image";

interface BlurSaveTextFieldProps {
  value: string;
  /** The stored value. Blur saves only when `value` differs from it. */
  savedValue: string;
  placeholder: string;
  onChange: (value: string) => void;
  onSave: () => void;
}

/** A text field that saves on blur, and blurs on Enter. */
function BlurSaveTextField({
  value,
  savedValue,
  placeholder,
  onChange,
  onSave,
}: BlurSaveTextFieldProps) {
  return (
    <InputTypeIn
      placeholder={placeholder}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.currentTarget.blur();
        }
      }}
      onBlur={() => {
        if (value !== savedValue) onSave();
      }}
    />
  );
}

export default function AccountSettings() {
  const t = useTranslations("settings");
  const tProfile = useTranslations("profile");
  const { appName } = useSettings();
  const {
    user,
    isAdmin,
    authTypeMetadata,
    refreshUser,
    updateUserPersonalization,
  } = useUser();
  const [isPhotoBusy, setIsPhotoBusy] = useState(false);
  const [isPhotoMenuOpen, setIsPhotoMenuOpen] = useState(false);
  // The picked photo, while the crop dialog is open.
  const [photoToCrop, setPhotoToCrop] = useState<File | null>(null);
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

  const savedName = user?.personalization?.name ?? "";
  const savedPreferredName = user?.personalization?.preferred_name ?? "";
  const savedRole = user?.personalization?.role ?? "";
  // "Other" picked before any text is typed.
  const [otherRolePicked, setOtherRolePicked] = useState(false);
  // A stored role outside the option list shows as "Other" with its text.
  const isOtherRole =
    otherRolePicked || (savedRole !== "" && !WORK_ROLE_VALUES.has(savedRole));

  const profileImageUrl = buildUserProfileImageUrl(user);

  // Refreshing the user updates every avatar that reads it.
  async function changeProfileImage(request: () => Promise<Response>) {
    setIsPhotoBusy(true);
    try {
      const response = await request();
      if (!response.ok) {
        throw new Error(`Profile photo request failed: ${response.status}`);
      }
      await refreshUser();
    } catch (error) {
      console.error(error);
      toast.error(t("profile.photo.toasts.updateFailed"));
    } finally {
      setIsPhotoBusy(false);
    }
  }

  const { fileInput: photoFileInput, openFilePicker: openPhotoPicker } =
    useImageDropzone({
      accept: {
        "image/png": [".png"],
        "image/jpeg": [".jpg", ".jpeg"],
        "image/webp": [".webp"],
      },
      disabled: isPhotoBusy,
      onImageAccepted: (file) => {
        // The backend upload cap.
        if (file.size > 10 * 1024 * 1024) {
          toast.error(t("profile.photo.errors.tooLarge"));
          return;
        }
        setPhotoToCrop(file);
      },
      onImageRejected: () => toast.error(t("profile.photo.errors.invalidType")),
    });

  function handleWorkRoleChange(value: string) {
    if (value === OTHER_WORK_ROLE) {
      setOtherRolePicked(true);
      // The free-text field saves the role on blur.
      updatePersonalizationField("role", "");
      return;
    }
    setOtherRolePicked(false);
    void handleSavePersonalization({ role: value });
  }

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
        useUnseenRuns.getState().clearAll();
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

      {photoFileInput}
      {photoToCrop && (
        <ProfilePhotoCropModal
          file={photoToCrop}
          onCancel={() => setPhotoToCrop(null)}
          onSave={(photo) => {
            setPhotoToCrop(null);
            const formData = new FormData();
            formData.append("file", photo);
            void changeProfileImage(() =>
              fetch(PROFILE_IMAGE_API, { method: "POST", body: formData })
            );
          }}
        />
      )}

      <Section gap={8}>
        <SettingsSection title={t("profile.title")}>
          <InputHorizontal
            title={t("profile.photo.title")}
            description={t("profile.photo.description")}
            center
          >
            {/* One trigger in both states, so it keeps focus when the photo
                changes. Without a photo, a click picks one and opens no menu. */}
            <Dropdown
              open={isPhotoMenuOpen}
              onOpenChange={setIsPhotoMenuOpen}
              disabled={!profileImageUrl || isPhotoBusy}
              width={40}
              align="end"
            >
              <Dropdown.Trigger asChild>
                <AvatarButton
                  size={PROFILE_PHOTO_SIZE_PX}
                  busy={isPhotoBusy}
                  {...(profileImageUrl
                    ? {
                        "aria-label": t("profile.photo.editButton.ariaLabel"),
                      }
                    : {
                        "aria-label": t("profile.photo.uploadButton.ariaLabel"),
                        "aria-haspopup": undefined,
                        "aria-expanded": undefined,
                        "aria-controls": undefined,
                        onClick: () => {
                          if (!isPhotoBusy) openPhotoPicker();
                        },
                      })}
                >
                  <UserAvatar
                    name={getUserAddressedName(user)}
                    email={getUserEmail(user)}
                    imageUrl={profileImageUrl}
                    size={PROFILE_PHOTO_SIZE_PX}
                  />
                </AvatarButton>
              </Dropdown.Trigger>
              <Dropdown.Data
                label={t("profile.photo.menu.label")}
                items={[
                  {
                    kind: "action",
                    id: "replace",
                    icon: SvgImage,
                    title: t("profile.photo.menu.replace.label"),
                    onSelect: openPhotoPicker,
                  },
                  {
                    kind: "action",
                    id: "remove",
                    icon: SvgTrash,
                    danger: true,
                    title: t("profile.photo.menu.remove.label"),
                    onSelect: () =>
                      void changeProfileImage(() =>
                        fetch(PROFILE_IMAGE_API, { method: "DELETE" })
                      ),
                  },
                ]}
              />
            </Dropdown>
          </InputHorizontal>
          <InputHorizontal
            title={t("profile.fullName.title")}
            description={t("profile.fullName.description")}
            center
            withLabel
            fillInput
            responsive
          >
            <BlurSaveTextField
              placeholder={t("profile.fullName.placeholder")}
              value={personalizationValues.name}
              savedValue={savedName}
              onChange={(value) => updatePersonalizationField("name", value)}
              onSave={() =>
                void handleSavePersonalization({
                  name: personalizationValues.name,
                })
              }
            />
          </InputHorizontal>
          <InputHorizontal
            title={t("profile.preferredName.title", { appName })}
            description={t("profile.preferredName.description", { appName })}
            center
            withLabel
            fillInput
            responsive
          >
            <BlurSaveTextField
              placeholder={t("profile.preferredName.placeholder")}
              value={personalizationValues.preferred_name}
              savedValue={savedPreferredName}
              onChange={(value) =>
                updatePersonalizationField("preferred_name", value)
              }
              onSave={() =>
                void handleSavePersonalization({
                  preferred_name: personalizationValues.preferred_name,
                })
              }
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
            <InputSingleSelect
              value={
                isOtherRole
                  ? OTHER_WORK_ROLE
                  : WORK_ROLE_VALUES.has(personalizationValues.role)
                    ? personalizationValues.role
                    : ""
              }
              onValueChange={handleWorkRoleChange}
              placeholder={t("profile.workRole.placeholder")}
              aria-label={t("profile.workRole.title")}
              options={[
                ...WORK_ROLE_OPTIONS.map((option) => ({
                  value: option.value,
                  title: tProfile(`workRole.${option.labelKey}.label`),
                })),
                {
                  value: OTHER_WORK_ROLE,
                  title: tProfile("workRole.other.label"),
                },
              ]}
            />
          </InputHorizontal>
          {isOtherRole && (
            <InputHorizontal
              title={t("profile.workRole.other.title")}
              center
              withLabel
              fillInput
              responsive
            >
              <BlurSaveTextField
                placeholder={t("profile.workRole.other.placeholder")}
                value={personalizationValues.role}
                savedValue={savedRole}
                onChange={(value) => updatePersonalizationField("role", value)}
                onSave={() =>
                  void handleSavePersonalization({
                    role: personalizationValues.role,
                  })
                }
              />
            </InputHorizontal>
          )}
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

        <SettingsSection title={t("organization.title")}>
          <InputHorizontal
            title={t("organization.role.title")}
            description={t("organization.role.description")}
            center
          >
            <Text as="p" font="main-ui-body" color="text-04">
              {isAdmin
                ? t("organization.role.admin")
                : user?.is_group_manager
                  ? t("organization.role.groupManager")
                  : t("organization.role.basic")}
            </Text>
          </InputHorizontal>
          {user?.tenant_id && (
            <InputHorizontal
              title={t("organization.tenantId.title")}
              description={t("organization.tenantId.description")}
              center
            >
              <Section flexDirection="row" gap={0.5} width="fit">
                <Text as="p" font="main-ui-body" color="text-04">
                  {user.tenant_id}
                </Text>
                <CopyButton
                  getCopyText={() => user.tenant_id ?? ""}
                  tooltip={t("organization.tenantId.copyTooltip")}
                />
              </Section>
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
