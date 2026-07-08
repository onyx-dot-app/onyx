"use client";

import { useMemo, useState } from "react";
import { mutate } from "swr";
import {
  Button,
  Card,
  InputTypeIn,
  MessageCard,
  Switch,
  Table,
  createTableColumns,
} from "@opal/components";
import {
  Content,
  IllustrationContent,
  InputHorizontal,
  SettingsLayouts,
} from "@opal/layouts";
import { SvgPlusCircle, SvgSimpleLoader } from "@opal/icons";
import SvgNoResult from "@opal/illustrations/no-result";
import { Section } from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import UserAvatar from "@/refresh-components/avatars/UserAvatar";
import { toast } from "@/hooks/useToast";
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
import { setUsersCraftAccess } from "./svc";

const PAGE_SIZE = 10;

// ---------------------------------------------------------------------------
// Columns
// ---------------------------------------------------------------------------

const tc = createTableColumns<UserRow>();

function buildBaseColumns() {
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
      weight: 40,
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
      weight: 20,
      cell: (role) => (
        <Text as="span" secondaryBody text03>
          {role ? (USER_ROLE_LABELS[role] ?? role) : "—"}
        </Text>
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
  const [isAdding, setIsAdding] = useState(false);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  // The default value pending confirmation, or null when no confirm is open.
  const [pendingDefault, setPendingDefault] = useState<boolean | null>(null);
  const [isSavingDefault, setIsSavingDefault] = useState(false);

  const realUsers = useMemo(() => users.filter((u) => u.id !== null), [users]);
  const exceptions = useMemo(
    () =>
      [...realUsers]
        .filter((u) => u.craft_enabled !== null)
        // Overrides doing work (opposite the default) sort first.
        .sort(
          (a, b) =>
            Number(a.craft_enabled === defaultEnabled) -
            Number(b.craft_enabled === defaultEnabled)
        ),
    [realUsers, defaultEnabled]
  );
  const candidates = useMemo(
    () => realUsers.filter((u) => u.craft_enabled === null),
    [realUsers]
  );
  const redundantExceptions = useMemo(
    () => exceptions.filter((u) => u.craft_enabled === defaultEnabled),
    [exceptions, defaultEnabled]
  );
  const enabledCount = defaultEnabled
    ? realUsers.length -
      exceptions.filter((u) => u.craft_enabled === false).length
    : exceptions.filter((u) => u.craft_enabled === true).length;

  const selectedEmails = useMemo(() => {
    const ids = new Set(selectedIds);
    return candidates
      .filter((u) => u.id !== null && ids.has(u.id))
      .map((u) => u.email);
  }, [candidates, selectedIds]);

  const exceptionColumns = useMemo(
    () => [
      ...buildBaseColumns(),
      tc.column("craft_enabled", {
        header: "Access",
        weight: 24,
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
    [defaultEnabled, refresh]
  );
  const candidateColumns = useMemo(() => buildBaseColumns(), []);

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

  async function applyBatch(emails: string[], craftEnabled: boolean | null) {
    try {
      await setUsersCraftAccess(emails, craftEnabled);
      refresh();
      return true;
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to update Craft access"
      );
      return false;
    }
  }

  async function confirmAdd() {
    const craftEnabled = !defaultEnabled;
    if (await applyBatch(selectedEmails, craftEnabled)) {
      toast.success(
        `Craft ${craftEnabled ? "enabled" : "disabled"} for ${selectedEmails.length} user${selectedEmails.length === 1 ? "" : "s"}`
      );
      setIsAdding(false);
      setSelectedIds([]);
      setSearchTerm("");
    }
  }

  async function clearRedundant() {
    const emails = redundantExceptions.map((u) => u.email);
    if (await applyBatch(emails, null)) {
      toast.success(
        `Cleared ${emails.length} exception${emails.length === 1 ? "" : "s"}`
      );
    }
  }

  const header = (
    <SettingsLayouts.Header
      icon={ADMIN_ROUTES.CRAFT.icon}
      title={ADMIN_ROUTES.CRAFT.title}
      description="Control who can use Craft, Onyx's agentic app builder."
      divider
    />
  );

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

  const addLabel = defaultEnabled ? "Disable Users" : "Enable Users";
  const confirmAddLabel = `${defaultEnabled ? "Disable" : "Enable"} ${selectedEmails.length} user${selectedEmails.length === 1 ? "" : "s"}`;

  return (
    <SettingsLayouts.Root>
      {header}
      <SettingsLayouts.Body>
        <Card border="solid" rounding="lg">
          <Section alignItems="stretch" gap={0.5}>
            <InputHorizontal
              title="Enable Craft by default"
              tag={{ title: "beta", color: "blue" }}
              description={
                defaultEnabled
                  ? "Craft is on for all users. Use the exceptions below to disable specific users."
                  : "Craft is off for everyone. Only users you enable below can use it — ideal while piloting the beta."
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
                ? " "
                : `Currently: ${enabledCount} of ${realUsers.length} users have access`}
            </Text>
          </Section>
        </Card>

        {redundantExceptions.length > 0 && (
          <MessageCard
            variant="info"
            title={`${redundantExceptions.length} exception${redundantExceptions.length === 1 ? "" : "s"} match the workspace default`}
            description="They have no effect right now, but pin those users' access if the default changes."
            rightChildren={
              <Button
                prominence="secondary"
                size="sm"
                onClick={() => {
                  void clearRedundant();
                }}
              >
                Clear Redundant
              </Button>
            }
          />
        )}

        <Section alignItems="stretch" gap={0.75}>
          <Content
            sizePreset="main-content"
            variant="section"
            title={`Per-user exceptions${exceptions.length > 0 ? ` · ${exceptions.length}` : ""}`}
            description="Exceptions always win over the default and stay pinned if the default changes."
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
              <div className="flex items-center gap-2">
                <div className="flex-1">
                  <InputTypeIn
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                    placeholder={
                      isAdding ? "Search users..." : "Search exceptions..."
                    }
                    searchIcon
                  />
                </div>
                {isAdding ? (
                  <>
                    <Button
                      prominence="secondary"
                      onClick={() => {
                        setIsAdding(false);
                        setSelectedIds([]);
                        setSearchTerm("");
                      }}
                    >
                      Cancel
                    </Button>
                    <Button
                      disabled={selectedEmails.length === 0}
                      onClick={() => {
                        void confirmAdd();
                      }}
                    >
                      {confirmAddLabel}
                    </Button>
                  </>
                ) : (
                  <Button
                    icon={SvgPlusCircle}
                    prominence="secondary"
                    onClick={() => {
                      setIsAdding(true);
                      setSearchTerm("");
                    }}
                  >
                    {addLabel}
                  </Button>
                )}
              </div>

              {isAdding ? (
                <Table
                  data={candidates}
                  columns={candidateColumns}
                  getRowId={(row) => row.id ?? row.email}
                  pageSize={PAGE_SIZE}
                  searchTerm={searchTerm}
                  selectionBehavior="multi-select"
                  onSelectionChange={setSelectedIds}
                  footer={{}}
                  emptyState={
                    <IllustrationContent
                      illustration={SvgNoResult}
                      title="No users found"
                      description="Only users who have signed in can be given an exception."
                    />
                  }
                />
              ) : (
                <Table
                  data={exceptions}
                  columns={exceptionColumns}
                  getRowId={(row) => row.id ?? row.email}
                  pageSize={PAGE_SIZE}
                  searchTerm={searchTerm}
                  footer={{}}
                  emptyState={
                    <IllustrationContent
                      illustration={SvgNoResult}
                      title="No exceptions"
                      description={
                        defaultEnabled
                          ? `Everyone follows the default. Use "${addLabel}" to make exceptions.`
                          : `No one can use Craft yet. Click "${addLabel}" to start a pilot.`
                      }
                    />
                  }
                />
              )}
            </>
          )}
        </Section>
      </SettingsLayouts.Body>

      {pendingDefault !== null && (
        <ConfirmationModalLayout
          icon={ADMIN_ROUTES.CRAFT.icon}
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
                  exceptions.filter((u) => u.craft_enabled === false).length > 0
                    ? `, except the ${exceptions.filter((u) => u.craft_enabled === false).length} explicitly disabled below`
                    : ""
                }. Craft runs code in cloud sandboxes and consumes LLM credits.`
              : `Access is removed for everyone${
                  exceptions.filter((u) => u.craft_enabled === true).length > 0
                    ? ` except the ${exceptions.filter((u) => u.craft_enabled === true).length} users explicitly enabled below`
                    : ""
                }. In-progress sessions are unaffected.`}
          </Text>
        </ConfirmationModalLayout>
      )}
    </SettingsLayouts.Root>
  );
}
