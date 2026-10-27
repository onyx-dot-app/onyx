"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import { useFocusOnMount, useGridNavigation, useHotkey } from "@opal/hooks";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import useSWR from "swr";
import { SvgExternalLink, SvgUsers } from "@opal/icons";
import { Button, MessageCard } from "@opal/components";
import { SettingsLayouts } from "@opal/layouts";
import { errorHandlingFetcher } from "@/lib/fetcher";
import type { UserGroup } from "@/lib/types";
import { Permission } from "@/lib/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useUser } from "@/providers/UserProvider";
import { hasPermission } from "@/lib/permissions/utils";
import { can } from "@/lib/permissions/resource-actions";
import GroupsList from "./GroupsList";
import AdminListHeader from "@/sections/admin/AdminListHeader";
import { useSettings } from "@/lib/settings/hooks";

function GroupsPage() {
  const t = useTranslations("admin.groups");
  const { appName } = useSettings();
  const router = useRouter();
  const [searchQuery, setSearchQuery] = useState("");
  const { user } = useUser();

  // Create is global-only (route has no allow_scope); gate on the global token, not
  // admin_capabilities, which would show it to scoped managers who'd then 403.
  const canCreateGroup = hasPermission(
    user?.effective_permissions ?? [],
    Permission.MANAGE_USER_GROUPS
  );

  const {
    data: groups,
    error,
    isLoading,
  } = useSWR<UserGroup[]>(
    SWR_KEYS.adminUserGroupsWithDefault,
    errorHandlingFetcher
  );

  // The list is READ_USER_GROUPS-scoped (implied by MANAGE_LLMS etc.), so filter to
  // manageable groups — else a read-only holder sees groups with no open action.
  // `manage_members` is the broadest action, and the only one a default group keeps —
  // so this also hides Admin/Basic from non-full-admins.
  const manageableGroups = useMemo(
    () => (groups ?? []).filter((group) => can(group, "manage_members")),
    [groups]
  );

  const searchInputRef = useRef<HTMLInputElement | null>(null);
  // The field mounts once the groups load, so it takes focus then, as the
  // connectors catalog's does on arrival.
  const focusOnMount = useFocusOnMount<HTMLInputElement>();
  const setSearchInput = useCallback(
    (input: HTMLInputElement | null) => {
      searchInputRef.current = input;
      focusOnMount(input);
    },
    [focusOnMount]
  );

  /**
   * Moves focus to the search field, with the caret at the end. A query
   * passed in replaces the current one.
   */
  function focusSearch(nextQuery?: string) {
    const input = searchInputRef.current;
    if (!input) return;
    if (nextQuery !== undefined) setSearchQuery(nextQuery);
    input.focus();
    // After React writes the new value.
    requestAnimationFrame(() => {
      const end = input.value.length;
      input.setSelectionRange(end, end);
    });
  }

  useHotkey("/", () => focusSearch());

  // Up and Down move between the cards, Tab follows them in order, and Enter
  // opens one. Leaving the top card, Escape, or typing returns to search.
  const { ref: listRef, focusFirst } = useGridNavigation({
    itemSelector: "[data-card]",
    onExit: (direction) => {
      if (direction === "up") focusSearch();
    },
    onEscape: () => focusSearch(),
    onTypeAhead: (character) => {
      if (character === "/") return false;
      focusSearch(searchQuery + character);
    },
  });

  // Enter or ArrowDown moves to the first card. Escape clears the query,
  // then, on an empty field, leaves it.
  function handleSearchKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    // Keys that build or cancel an IME composition belong to the IME.
    if (e.nativeEvent.isComposing) return;
    if (e.key === "Escape") {
      e.preventDefault();
      if (searchQuery !== "") setSearchQuery("");
      else e.currentTarget.blur();
      return;
    }
    if ((e.key === "Enter" || e.key === "ArrowDown") && focusFirst()) {
      e.preventDefault();
    }
  }

  return (
    <SettingsLayouts.Root
      loading={isLoading}
      error={error ? t("list.loadError.description") : false}
    >
      <div data-testid="groups-page-heading">
        <SettingsLayouts.Header icon={SvgUsers} title={t("page.title")} divider>
          <MessageCard
            variant="info"
            title={t("permissionsChanged.title")}
            description={t("permissionsChanged.description", { appName })}
            outerPadding={1}
            innerPadding={1}
            // Matches the md button's padding, so its label lines up with the
            // title.
            contentPadding={1}
            rightChildren={
              <Button
                icon={SvgExternalLink}
                size="md"
                onClick={() =>
                  window.open(
                    "https://docs.onyx.app/admins/permissions/whats_changing",
                    "_blank",
                    "noopener,noreferrer"
                  )
                }
              >
                {t("permissionsChanged.learnMore.label")}
              </Button>
            }
          />
        </SettingsLayouts.Header>
      </div>

      {/* The search row's own padding spaces it from the cards. */}
      <SettingsLayouts.Body gap={0}>
        <AdminListHeader
          hasItems={!isLoading && !error && manageableGroups.length > 0}
          searchQuery={searchQuery}
          onSearchQueryChange={setSearchQuery}
          placeholder={t("list.search.placeholder")}
          emptyStateText={t("list.empty.text")}
          onAction={
            canCreateGroup
              ? () => router.push("/admin/groups/create")
              : undefined
          }
          actionLabel={canCreateGroup ? t("list.newGroup.label") : undefined}
          inputRef={setSearchInput}
          onSearchKeyDown={handleSearchKeyDown}
        />

        {!isLoading && !error && groups && (
          <div ref={listRef}>
            <GroupsList groups={manageableGroups} searchQuery={searchQuery} />
          </div>
        )}
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}

export default GroupsPage;
