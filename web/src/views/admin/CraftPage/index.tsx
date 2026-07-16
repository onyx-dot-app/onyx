"use client";

import { useMemo, useState } from "react";
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
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import UserAvatar from "@/refresh-components/avatars/UserAvatar";
import { SWR_KEYS } from "@/lib/swr-keys";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { useSettings } from "@/lib/settings/hooks";
import { toSettings } from "@/lib/settings/types";
import { updateAdminSettings } from "@/lib/settings/svc";
import useAdminUsers from "@/hooks/useAdminUsers";
import { USER_ROLE_LABELS } from "@/lib/types";
import type { User } from "@/lib/types";
import type { UserRow } from "@/views/admin/UsersPage/interfaces";
import AccessCell from "./AccessCell";

const PAGE_SIZE = 10;

// ---------------------------------------------------------------------------
// Columns
// ---------------------------------------------------------------------------

const tc = createTableColumns<UserRow>();

function buildColumns(defaultEnabled: boolean, onMutate: () => void) {
  return [
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
      header: "User",
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
    tc.column("role", {
      header: "Role",
      weight: 24,
      cell: (role) => (
        <Text as="span" secondaryBody text03>
          {role ? (USER_ROLE_LABELS[role] ?? role) : "—"}
        </Text>
      ),
    }),
    tc.column("craft_enabled", {
      header: "Access",
      weight: 16,
      enableSorting: false,
      cell: (_value, row) => (
        <AccessCell
          user={row}
          defaultEnabled={defaultEnabled}
          onMutate={onMutate}
        />
      ),
    }),
  ];
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function CraftPage() {
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
    () => buildColumns(defaultEnabled, refresh),
    [defaultEnabled, refresh]
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
          ? "Craft is now enabled by default"
          : "Craft is now disabled by default"
      );
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to update settings"
      );
    } finally {
      setIsSavingDefault(false);
      setPendingDefault(null);
    }
  }

  const header = (
    <SettingsLayouts.Header
      icon={ADMIN_ROUTES.CRAFT_ACCESS.icon}
      title={ADMIN_ROUTES.CRAFT_ACCESS.title}
      description="Control who can use Craft, Onyx's agentic app builder."
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
              Failed to load settings. Please try refreshing the page.
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
            title="Craft isn't available on this deployment"
            description="Craft is enabled per deployment by Onyx. Contact your Onyx representative to get access."
          />
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }

  return (
    <SettingsLayouts.Root>
      {header}
      <SettingsLayouts.Body>
        <Card border="solid" rounding="lg">
          <Section alignItems="stretch" gap={0.5}>
            <InputHorizontal
              title="Enable Craft by default"
              tag={{ title: "beta", color: "blue" }}
              description={`Craft is ${defaultEnabled ? "on" : "off"} for everyone. Toggle individual users below.`}
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
                : `Currently: ${enabledCount} of ${realUsers.length} users have access`}
            </Text>
          </Section>
        </Card>

        <Section alignItems="stretch" gap={0.75}>
          <Content
            sizePreset="main-content"
            variant="section"
            title="Per-user access"
            description="Users you toggle away from the workspace default keep their setting if the default changes."
          />

          {isLoading && (
            <div className="flex justify-center py-12">
              <SvgSimpleLoader className="h-6 w-6" />
            </div>
          )}
          {error ? (
            <Text as="p" secondaryBody text03>
              Failed to load users. Please try refreshing the page.
            </Text>
          ) : null}

          {!isLoading && !error && (
            <>
              <InputTypeIn
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder="Search users..."
                searchIcon
              />
              <Table
                data={realUsers}
                columns={columns}
                getRowId={(row) => row.id ?? row.email}
                pageSize={PAGE_SIZE}
                searchTerm={searchTerm}
                footer={{ units: "users" }}
                emptyState={
                  <IllustrationContent
                    illustration={SvgNoResult}
                    title="No users found"
                    description="No users match your search."
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
              ? "Enable Craft for all users?"
              : "Disable Craft by default?"
          }
          onClose={isSavingDefault ? undefined : () => setPendingDefault(null)}
          submit={
            <Button
              disabled={isSavingDefault}
              onClick={() => {
                void saveDefault(pendingDefault);
              }}
            >
              {pendingDefault ? "Enable for Everyone" : "Disable by Default"}
            </Button>
          }
        >
          <Text as="p" text03>
            {pendingDefault
              ? `All ${realUsers.length} users get access${
                  explicitlyDisabled > 0
                    ? `, except the ${explicitlyDisabled} toggled off below`
                    : ""
                }. Craft agents run in sandboxes and can act on your behalf with your authorization and approvals.`
              : `Access is removed for everyone${
                  explicitlyEnabled > 0
                    ? ` except the ${explicitlyEnabled} users toggled on below`
                    : ""
                }. In-progress sessions are unaffected.`}
          </Text>
        </ConfirmationModalLayout>
      )}
    </SettingsLayouts.Root>
  );
}
