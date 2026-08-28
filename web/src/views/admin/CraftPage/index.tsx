"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { mutate } from "swr";
import {
  Button,
  Card,
  InputTypeIn,
  Switch,
  Table,
  createTableColumns,
} from "@opal/components";
import {
  Content,
  IllustrationContent,
  InputHorizontal,
  SettingsLayouts,
  toast,
} from "@opal/layouts";
import { SvgSimpleLoader } from "@opal/icons";
import SvgNoResult from "@opal/illustrations/no-result";
import { Section } from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";
import { ConfirmationModalLayout } from "@opal/layouts";
import UserAvatar from "@/refresh-components/avatars/UserAvatar";
import { SWR_KEYS } from "@/lib/swr-keys";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { useSettings } from "@/lib/settings/hooks";
import { toSettings } from "@/lib/settings/types";
import { updateAdminSettings } from "@/lib/settings/svc";
import useAdminUsers from "@/hooks/useAdminUsers";
import type { User } from "@/lib/types";
import type { UserRow } from "@/views/admin/UsersPage/interfaces";
import GroupsCell from "@/views/admin/UsersPage/GroupsCell";
import AccessCell from "./AccessCell";

const PAGE_SIZE = 10;

// ---------------------------------------------------------------------------
// Columns
// ---------------------------------------------------------------------------

const tc = createTableColumns<UserRow>();

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function CraftPage() {
  const t = useTranslations("admin.craft");
  const settings = useSettings();
  const craftAvailable = settings?.onyx_craft_available === true;
  const defaultEnabled = settings?.craft_default_enabled !== false;

  const { users, isLoading, error, refresh } = useAdminUsers();

  const [searchTerm, setSearchTerm] = useState("");
  // The default value pending confirmation, or null when no confirm is open.
  const [pendingDefault, setPendingDefault] = useState<boolean | null>(null);
  const [isSavingDefault, setIsSavingDefault] = useState(false);

  const realUsers = useMemo(() => users.filter((u) => u.id !== null), [users]);
  const explicitlyEnabled = realUsers.filter(
    (u) => u.craft_enabled === true
  ).length;
  const explicitlyDisabled = realUsers.filter(
    (u) => u.craft_enabled === false
  ).length;
  const enabledCount = defaultEnabled
    ? realUsers.length - explicitlyDisabled
    : explicitlyEnabled;

  const columns = useMemo(
    () => [
      tc.qualifier({
        content: "icon",
        iconSize: "lg",
        getContent: (row) => {
          const user = {
            email: row.email,
            personalization: row.personal_name
              ? { name: row.personal_name }
              : undefined,
          } as User;
          return (props) => <UserAvatar user={user} size={props.size} />;
        },
      }),
      tc.column("email", {
        header: t("table.userColumn.header"),
        weight: 44,
        cell: (email, row) => (
          <Content
            sizePreset="main-ui"
            variant="section"
            title={row.personal_name ?? email}
            description={row.personal_name ? email : undefined}
          />
        ),
      }),
      tc.column("groups", {
        header: t("table.groupsColumn.header"),
        weight: 24,
        enableSorting: false,
        cell: (value, row) => (
          <GroupsCell groups={value} user={row} onMutate={refresh} />
        ),
      }),
      tc.column("craft_enabled", {
        header: t("table.accessColumn.header"),
        weight: 16,
        enableSorting: false,
        cell: (_value, row) => (
          <AccessCell
            user={row}
            defaultEnabled={defaultEnabled}
            onMutate={refresh}
          />
        ),
      }),
    ],
    [defaultEnabled, refresh, t]
  );

  async function saveDefault(checked: boolean) {
    if (!settings) return;
    setIsSavingDefault(true);
    try {
      await updateAdminSettings({
        ...toSettings(settings),
        craft_default_enabled: checked,
      });
      await mutate(SWR_KEYS.settings);
      toast.success(
        checked
          ? t("defaultToggle.enabledSuccess.message")
          : t("defaultToggle.disabledSuccess.message")
      );
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t("saveError.message"));
    } finally {
      setIsSavingDefault(false);
      setPendingDefault(null);
    }
  }

  const header = (
    <SettingsLayouts.Header
      icon={ADMIN_ROUTES.CRAFT_ACCESS.icon}
      title={t("header.title")}
      description={t("header.description")}
      divider
    />
  );

  // useSettings returns a default object while loading (and on error), which
  // lacks onyx_craft_available — don't misreport Craft as unavailable.
  if (settings.isLoading || settings.error) {
    return (
      <SettingsLayouts.Root>
        {header}
        <SettingsLayouts.Body>
          {settings.error ? (
            <Text as="p" secondaryBody text03>
              {t("settingsLoadError.description")}
            </Text>
          ) : (
            <div className="flex justify-center py-12">
              <SvgSimpleLoader className="h-6 w-6" />
            </div>
          )}
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }

  if (!craftAvailable) {
    return (
      <SettingsLayouts.Root>
        {header}
        <SettingsLayouts.Body>
          <IllustrationContent
            illustration={SvgNoResult}
            title={t("unavailable.title")}
            description={t("unavailable.description")}
          />
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }

  return (
    <SettingsLayouts.Root>
      {header}
      <SettingsLayouts.Body>
        <Card border="solid" rounding={4}>
          <Section alignItems="stretch" gap={2}>
            <InputHorizontal
              title={t("defaultToggle.title")}
              tag={{ title: t("defaultToggle.betaTag.label"), color: "blue" }}
              description={
                defaultEnabled
                  ? t("defaultToggle.enabled.description")
                  : t("defaultToggle.disabled.description")
              }
              withLabel
            >
              <Switch
                checked={defaultEnabled}
                disabled={isSavingDefault}
                onCheckedChange={(checked) => setPendingDefault(checked)}
              />
            </InputHorizontal>
            <Text as="p" secondaryBody text03>
              {isLoading
                ? " "
                : t("accessSummary.description", {
                    enabledCount,
                    total: realUsers.length,
                  })}
            </Text>
          </Section>
        </Card>

        <Section alignItems="stretch" gap={3}>
          <Content
            sizePreset="main-content"
            variant="section"
            title={t("perUserAccess.title")}
            description={t("perUserAccess.description")}
          />

          {isLoading && (
            <div className="flex justify-center py-12">
              <SvgSimpleLoader className="h-6 w-6" />
            </div>
          )}
          {error ? (
            <Text as="p" secondaryBody text03>
              {t("usersLoadError.description")}
            </Text>
          ) : null}

          {!isLoading && !error && (
            <>
              <InputTypeIn
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder={t("search.placeholder")}
                searchIcon
              />
              <Table
                data={realUsers}
                columns={columns}
                getRowId={(row) => row.id ?? row.email}
                pageSize={PAGE_SIZE}
                searchTerm={searchTerm}
                footer={{ units: t("table.footer.units") }}
                emptyState={
                  <IllustrationContent
                    illustration={SvgNoResult}
                    title={t("emptyState.title")}
                    description={t("emptyState.description")}
                  />
                }
              />
            </>
          )}
        </Section>
      </SettingsLayouts.Body>

      {pendingDefault !== null && (
        <ConfirmationModalLayout
          icon={ADMIN_ROUTES.CRAFT_ACCESS.icon}
          title={
            pendingDefault
              ? t("confirmModal.enableHeader.title")
              : t("confirmModal.disableHeader.title")
          }
          onClose={isSavingDefault ? undefined : () => setPendingDefault(null)}
          submit={
            <Button
              disabled={isSavingDefault}
              onClick={() => {
                void saveDefault(pendingDefault);
              }}
            >
              {pendingDefault
                ? t("confirmModal.enableButton.label")
                : t("confirmModal.disableButton.label")}
            </Button>
          }
        >
          <Text as="p" text03>
            {pendingDefault
              ? explicitlyDisabled > 0
                ? t("confirmModal.enableBody.withExclusions.description", {
                    total: realUsers.length,
                    excludedCount: explicitlyDisabled,
                  })
                : t("confirmModal.enableBody.description", {
                    total: realUsers.length,
                  })
              : explicitlyEnabled > 0
                ? t("confirmModal.disableBody.withExceptions.description", {
                    enabledCount: explicitlyEnabled,
                  })
                : t("confirmModal.disableBody.description")}
          </Text>
        </ConfirmationModalLayout>
      )}
    </SettingsLayouts.Root>
  );
}
