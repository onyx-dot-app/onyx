"use client";

import React, { useState, useMemo, useCallback, useRef } from "react";
import { useLocale, useTranslations } from "next-intl";
import type { Route } from "next";
import { useQueryController } from "@/providers/QueryControllerProvider";
import { useAppPosition } from "@/lib/navigation/hooks";
import { useHotkey } from "@opal/hooks";
import { Section, useSidebarState } from "@opal/layouts";
import useBrowserInfo from "@/hooks/useBrowserInfo";
import { CHAT_SHORTCUTS } from "@/lib/shortcuts/constants";
import { useChatShortcutActions } from "@/lib/shortcuts/hooks";
import { formatHotkey, isModalOpen } from "@/lib/shortcuts/utils";
import CommandMenu, {
  useCommandMenuContext,
} from "@/refresh-components/commandmenu/CommandMenu";
import { Text } from "@opal/components";
import { timeAgo } from "@opal/time";
import { highlightMatch } from "@/lib/sidebar/utils";
import useChatSearchOptimistic from "@/lib/sidebar/hooks";
import {
  SvgEditBig,
  SvgBubbleText,
  SvgArrowUpDown,
  SvgKeystroke,
  SvgSidebar,
  SvgCpu,
  SvgChevronUp,
  SvgChevronDown,
} from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";

/**
 * Dynamic footer that shows contextual action labels based on highlighted item type
 */
function DynamicFooter() {
  const t = useTranslations("sidebar");
  const { highlightedItemType } = useCommandMenuContext();

  // "Show all" for filters, "Open" for everything else (items, actions, or no highlight)
  const actionLabel =
    highlightedItemType === "filter"
      ? t("chatSearch.footer.showAllAction.label")
      : t("chatSearch.footer.openAction.label");

  return (
    <CommandMenu.Footer
      leftActions={
        <>
          <CommandMenu.FooterAction
            icon={SvgArrowUpDown}
            label={t("chatSearch.footer.selectAction.label")}
          />
          <CommandMenu.FooterAction icon={SvgKeystroke} label={actionLabel} />
        </>
      }
    />
  );
}

interface ChatSearchCommandMenuProps {
  /** Renders the control that opens the menu. `isOpen` lets it show a selected state. */
  trigger: (open: () => void, isOpen: boolean) => React.ReactNode;
}

interface ShortcutAction {
  value: string;
  icon: IconFunctionComponent;
  label: string;
  hotkey: string;
  run: () => void;
}

export default function ChatSearchCommandMenu({
  trigger,
}: ChatSearchCommandMenuProps) {
  const t = useTranslations("sidebar");
  const locale = useLocale();
  const [open, setOpen] = useState(false);
  const [searchValue, setSearchValue] = useState("");
  const [activeFilter, setActiveFilter] = useState<"all" | "chats">("all");
  const appPosition = useAppPosition();
  const { state } = useQueryController();
  const showingSearch =
    state.phase === "searching" ||
    state.phase === "search-results" ||
    (appPosition.isNewSession() &&
      state.phase === "idle" &&
      state.appMode === "search");

  // Constants for preview limits
  const PREVIEW_CHATS_LIMIT = 4;

  // Determine if we should enable optimistic search (when searching or viewing chats filter)
  const shouldUseOptimisticSearch =
    searchValue.trim().length > 0 || activeFilter === "chats";

  // Use optimistic search hook for chat sessions
  const {
    results: filteredChats,
    isSearching,
    hasMore,
    isLoadingMore,
    sentinelRef,
  } = useChatSearchOptimistic({
    searchQuery: searchValue,
    enabled: shouldUseOptimisticSearch,
  });

  // Compute displayed items based on filter state
  const displayedChats = useMemo(() => {
    if (activeFilter === "all" && !searchValue.trim()) {
      return filteredChats.slice(0, PREVIEW_CHATS_LIMIT);
    }
    return filteredChats;
  }, [filteredChats, activeFilter, searchValue]);

  // Header filters for showing active filter as a chip
  const headerFilters = useMemo(() => {
    if (activeFilter === "chats") {
      return [{ id: "chats", label: t("chatSearch.sessionsFilter.label") }];
    }
    return [];
  }, [activeFilter, t]);

  const handleFilterRemove = useCallback(() => {
    setActiveFilter("all");
  }, []);

  const restoreFocusRef = useRef<HTMLElement | null>(null);
  const handleOpenChange = useCallback((newOpen: boolean) => {
    if (newOpen) {
      const focused = document.activeElement;
      restoreFocusRef.current = focused instanceof HTMLElement ? focused : null;
    } else {
      setSearchValue("");
      setActiveFilter("all");
    }
    setOpen(newOpen);
  }, []);

  const handleOpen = useCallback(
    () => handleOpenChange(true),
    [handleOpenChange]
  );
  const handleChatSelect = useCallback(
    (chatId: string) => {
      appPosition.openChat(chatId);
      handleOpenChange(false);
    },
    [appPosition, handleOpenChange]
  );

  const handleEmptyBackspace = useCallback(() => {
    if (activeFilter !== "all") {
      // Remove active filter, return to root menu
      setActiveFilter("all");
    } else {
      // No filter active, close the menu
      handleOpenChange(false);
    }
  }, [activeFilter, handleOpenChange]);

  const hasSearchValue = searchValue.trim().length > 0;

  useHotkey(CHAT_SHORTCUTS.commandPalette, () => handleOpenChange(!open), {
    whileTyping: true,
    shouldHandle: () => open || !isModalOpen(),
  });

  const { isMac } = useBrowserInfo();
  const { setFolded } = useSidebarState();
  const shortcutActions = useChatShortcutActions();
  const keyNames = {
    ctrl: t("chatSearch.keys.ctrl"),
    alt: t("chatSearch.keys.alt"),
    shift: t("chatSearch.keys.shift"),
  };
  const shortcutLabel = (hotkey: string) =>
    formatHotkey(hotkey, isMac, keyNames);

  // Actions run after the menu has returned focus, so a popover they open
  // does not close at once.
  const afterCloseRef = useRef<(() => void) | null>(null);
  const handleCloseAutoFocus = (event: Event) => {
    const target = restoreFocusRef.current;
    restoreFocusRef.current = null;
    if (target?.isConnected) {
      event.preventDefault();
      target.focus();
    }
    const action = afterCloseRef.current;
    afterCloseRef.current = null;
    action?.();
  };

  const shortcutItems: ShortcutAction[] = [
    {
      value: "new-session",
      icon: SvgEditBig,
      label: t("chatSearch.newSession.label"),
      hotkey: CHAT_SHORTCUTS.newChat,
      run: shortcutActions.newChat,
    },
    {
      value: "toggle-sidebar",
      icon: SvgSidebar,
      label: t("chatSearch.shortcuts.toggleSidebar.label"),
      hotkey: CHAT_SHORTCUTS.toggleSidebar,
      run: () => setFolded((folded) => !folded),
    },
    {
      value: "change-model",
      icon: SvgCpu,
      label: t("chatSearch.shortcuts.changeModel.label"),
      hotkey: CHAT_SHORTCUTS.openModelPicker,
      run: shortcutActions.toggleModelPicker,
    },
    {
      value: "previous-chat",
      icon: SvgChevronUp,
      label: t("chatSearch.shortcuts.previousChat.label"),
      hotkey: CHAT_SHORTCUTS.previousChat,
      run: shortcutActions.previousChat,
    },
    {
      value: "next-chat",
      icon: SvgChevronDown,
      label: t("chatSearch.shortcuts.nextChat.label"),
      hotkey: CHAT_SHORTCUTS.nextChat,
      run: shortcutActions.nextChat,
    },
  ];
  const searchTerm = searchValue.trim().toLowerCase();
  const visibleShortcutItems =
    activeFilter === "all"
      ? shortcutItems.filter(
          (item) =>
            !(showingSearch && item.value === "change-model") &&
            item.label.toLowerCase().includes(searchTerm)
        )
      : [];

  return (
    <>
      {trigger(handleOpen, open)}

      <CommandMenu open={open} onOpenChange={handleOpenChange}>
        <CommandMenu.Content onCloseAutoFocus={handleCloseAutoFocus}>
          <CommandMenu.Header
            placeholder={t("chatSearch.searchInput.placeholder")}
            value={searchValue}
            onValueChange={setSearchValue}
            filters={headerFilters}
            onFilterRemove={handleFilterRemove}
            onClose={() => handleOpenChange(false)}
            onEmptyBackspace={handleEmptyBackspace}
          />

          <CommandMenu.List
            emptyMessage={
              hasSearchValue
                ? t("chatSearch.list.noResults.text")
                : t("chatSearch.list.empty.text")
            }
          >
            {displayedChats.length > 0 && (
              <>
                {searchValue.trim().length === 0 && (
                  <CommandMenu.Filter
                    value="recent-sessions"
                    onSelect={() => setActiveFilter("chats")}
                    isApplied={
                      activeFilter === "chats" ||
                      filteredChats.length <= PREVIEW_CHATS_LIMIT
                    }
                  >
                    {activeFilter === "chats"
                      ? t("chatSearch.recentFilter.label")
                      : t("chatSearch.recentSessionsFilter.label")}
                  </CommandMenu.Filter>
                )}
                {displayedChats.map((chat) => (
                  <CommandMenu.Item
                    key={chat.id}
                    value={`chat-${chat.id}`}
                    icon={SvgBubbleText}
                    rightContent={({ isHighlighted }) =>
                      isHighlighted ? (
                        <Text font="figure-keystroke" color="text-02">
                          ↵
                        </Text>
                      ) : (
                        <Text
                          font="secondary-body"
                          color="text-03"
                          data-testid="command-menu-timestamp"
                        >
                          {timeAgo(chat.time, locale) ?? ""}
                        </Text>
                      )
                    }
                    onSelect={() => handleChatSelect(chat.id)}
                  >
                    {highlightMatch(chat.label, searchValue)}
                  </CommandMenu.Item>
                ))}
                {/* Infinite scroll sentinel and loading indicator for chats */}
                {activeFilter === "chats" && hasMore && (
                  <div ref={sentinelRef} className="h-1" aria-hidden="true" />
                )}
                {activeFilter === "chats" && (isLoadingMore || isSearching) && (
                  <Section
                    flexDirection="row"
                    justifyContent="center"
                    alignItems="center"
                    height="fit"
                    padding={3}
                  >
                    <div className="h-5 w-5 animate-spin rounded-full border-2 border-solid border-text-04 border-t-text-02" />
                  </Section>
                )}
              </>
            )}

            {visibleShortcutItems.length > 0 && (
              <>
                <CommandMenu.Filter value="shortcuts" isApplied>
                  {t("chatSearch.shortcuts.title")}
                </CommandMenu.Filter>
                {visibleShortcutItems.map((item) => (
                  <CommandMenu.Action
                    key={item.value}
                    value={item.value}
                    icon={item.icon}
                    shortcut={shortcutLabel(item.hotkey)}
                    onSelect={() => {
                      afterCloseRef.current = item.run;
                    }}
                    defaultHighlight={hasSearchValue}
                  >
                    {item.label}
                  </CommandMenu.Action>
                ))}
              </>
            )}
          </CommandMenu.List>

          <DynamicFooter />
        </CommandMenu.Content>
      </CommandMenu>
    </>
  );
}
