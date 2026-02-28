"use client";

import { useRef, useCallback, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import * as InputLayouts from "@/layouts/input-layouts";
import { Section, AttachmentItemLayout } from "@/layouts/general-layouts";
import { Content, ContentAction } from "@opal/layouts";
import { Formik, Form } from "formik";
import * as Yup from "yup";
import {
  SvgArrowExchange,
  SvgKey,
  SvgLock,
  SvgMinusCircle,
  SvgTrash,
  SvgUnplug,
} from "@opal/icons";
import { getSourceMetadata } from "@/lib/sources";
import Card from "@/refresh-components/cards/Card";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";
import Button from "@/refresh-components/buttons/Button";
import Switch from "@/refresh-components/inputs/Switch";
import { useUser } from "@/providers/UserProvider";
import { useTheme } from "next-themes";
import { MemoryItem, ThemePreference } from "@/lib/types";
import useUserPersonalization from "@/hooks/useUserPersonalization";
import { toast } from "@/hooks/useToast";
import LLMPopover from "@/refresh-components/popovers/LLMPopover";
import { deleteAllChatSessions } from "@/app/app/services/lib";
import { useAuthType, useLlmManager } from "@/lib/hooks";
import useChatSessions from "@/hooks/useChatSessions";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import useFilter from "@/hooks/useFilter";
import CreateButton from "@/refresh-components/buttons/CreateButton";
import { Button as OpalButton } from "@opal/components";
import useFederatedOAuthStatus from "@/hooks/useFederatedOAuthStatus";
import useCCPairs from "@/hooks/useCCPairs";
import { ValidSources } from "@/lib/types";
import { ConnectorCredentialPairStatus } from "@/app/admin/connector/[ccPairId]/types";
import Separator from "@/refresh-components/Separator";
import Text from "@/refresh-components/texts/Text";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import Code from "@/refresh-components/Code";
import CharacterCount from "@/refresh-components/CharacterCount";
import { InputPrompt } from "@/app/app/interfaces";
import usePromptShortcuts from "@/hooks/usePromptShortcuts";
import ColorSwatch from "@/refresh-components/ColorSwatch";
import EmptyMessage from "@/refresh-components/EmptyMessage";
import Memories from "@/sections/settings/Memories";
import { FederatedConnectorOAuthStatus } from "@/components/chat/FederatedOAuthModal";
import {
  CHAT_BACKGROUND_OPTIONS,
  CHAT_BACKGROUND_NONE,
} from "@/lib/constants/chatBackgrounds";
import { SvgCheck } from "@opal/icons";
import { cn } from "@/lib/utils";
import { Interactive } from "@opal/core";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { useSettingsContext } from "@/providers/SettingsProvider";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import { useCloudSubscription } from "@/hooks/useCloudSubscription";

interface PAT {
  id: number;
  name: string;
  token_display: string;
  created_at: string;
  expires_at: string | null;
  last_used_at: string | null;
}

interface CreatedTokenState {
  id: number;
  token: string;
  name: string;
}

interface PATModalProps {
  isCreating: boolean;
  newTokenName: string;
  setNewTokenName: (name: string) => void;
  expirationDays: string;
  setExpirationDays: (days: string) => void;
  onClose: () => void;
  onCreate: () => void;
  createdToken: CreatedTokenState | null;
}

function PATModal({
  isCreating,
  newTokenName,
  setNewTokenName,
  expirationDays,
  setExpirationDays,
  onClose,
  onCreate,
  createdToken,
}: PATModalProps) {
  return (
    <ConfirmationModalLayout
      icon={SvgKey}
      title="Create Access Token"
      description="All API requests using this token will inherit your access permissions and be attributed to you as an individual."
      onClose={onClose}
      submit={
        !!createdToken?.token ? (
          <Button onClick={onClose}>Done</Button>
        ) : (
          <Button
            onClick={onCreate}
            disabled={isCreating || !newTokenName.trim()}
          >
            {isCreating ? "Creating Token..." : "Create Token"}
          </Button>
        )
      }
      hideCancel={!!createdToken}
    >
      <Section gap={1}>
        {/* Token Creation*/}
        {!!createdToken?.token ? (
          <InputLayouts.Vertical title="Token Value">
            <Code>{createdToken.token}</Code>
          </InputLayouts.Vertical>
        ) : (
          <>
            <InputLayouts.Vertical title="Token Name">
              <InputTypeIn
                placeholder="Name your token"
                value={newTokenName}
                onChange={(e) => setNewTokenName(e.target.value)}
                variant={isCreating ? "disabled" : undefined}
                autoComplete="new-password"
              />
            </InputLayouts.Vertical>
            <InputLayouts.Vertical
              title="Expires in"
              subDescription={
                expirationDays === "null"
                  ? undefined
                  : (() => {
                      const expiryDate = new Date();
                      expiryDate.setUTCDate(
                        expiryDate.getUTCDate() + parseInt(expirationDays)
                      );
                      expiryDate.setUTCHours(23, 59, 59, 999);
                      return `This token will expire at: ${expiryDate
                        .toISOString()
                        .replace("T", " ")
                        .replace(".999Z", " UTC")}`;
                    })()
              }
            >
              <InputSelect
                value={expirationDays}
                onValueChange={setExpirationDays}
                disabled={isCreating}
              >
                <InputSelect.Trigger placeholder="Select expiration" />
                <InputSelect.Content>
                  <InputSelect.Item value="7">7 days</InputSelect.Item>
                  <InputSelect.Item value="30">30 days</InputSelect.Item>
                  <InputSelect.Item value="365">365 days</InputSelect.Item>
                  <InputSelect.Item value="null">
                    No expiration
                  </InputSelect.Item>
                </InputSelect.Content>
              </InputSelect>
            </InputLayouts.Vertical>
          </>
        )}
      </Section>
    </ConfirmationModalLayout>
  );
}

function GeneralSettings() {
  const {
    user,
    updateUserPersonalization,
    updateUserThemePreference,
    updateUserChatBackground,
  } = useUser();
  const { theme, setTheme, systemTheme } = useTheme();
  const { refreshChatSessions } = useChatSessions();
  const router = useRouter();
  const pathname = usePathname();
  const [isDeleting, setIsDeleting] = useState(false);
  const [showDeleteConfirmation, setShowDeleteConfirmation] = useState(false);

  const {
    personalizationValues,
    updatePersonalizationField,
    handleSavePersonalization,
  } = useUserPersonalization(user, updateUserPersonalization, {
    onSuccess: () => toast.success("Personalization updated successfully"),
    onError: () => toast.error("Failed to update personalization"),
  });

  // Track initial values to detect changes
  const initialNameRef = useRef(personalizationValues.name);
  const initialRoleRef = useRef(personalizationValues.role);

  // Update refs when personalization values change from external source
  useEffect(() => {
    initialNameRef.current = personalizationValues.name;
    initialRoleRef.current = personalizationValues.role;
  }, [user?.personalization]);

  const handleDeleteAllChats = useCallback(async () => {
    setIsDeleting(true);
    try {
      const response = await deleteAllChatSessions();
      if (response.ok) {
        toast.success("All your chat sessions have been deleted.");
        await refreshChatSessions();
        setShowDeleteConfirmation(false);
      } else {
        throw new Error("Failed to delete all chat sessions");
      }
    } catch (error) {
      toast.error("Failed to delete all chat sessions");
    } finally {
      setIsDeleting(false);
    }
  }, [pathname, router, refreshChatSessions]);

  return (
    <>
      {showDeleteConfirmation && (
        <ConfirmationModalLayout
          icon={SvgTrash}
          title="Delete All Chats"
          onClose={() => setShowDeleteConfirmation(false)}
          submit={
            <Button
              danger
              onClick={() => {
                void handleDeleteAllChats();
              }}
              disabled={isDeleting}
            >
              {isDeleting ? "Deleting..." : "Delete"}
            </Button>
          }
        >
          <Section gap={0.5} alignItems="start">
            <Text>
              All your chat sessions and history will be permanently deleted.
              Deletion cannot be undone.
            </Text>
            <Text>Are you sure you want to delete all chats?</Text>
          </Section>
        </ConfirmationModalLayout>
      )}

      <Section gap={2}>
        <Section gap={0.75}>
          <Content
            title="Profile"
            sizePreset="main-content"
            variant="section"
            widthVariant="full"
          />
          <Card>
            <InputLayouts.Horizontal
              title="Full Name"
              description="We'll display this name in the app."
              center
            >
              <InputTypeIn
                placeholder="Your name"
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
                    void handleSavePersonalization();
                    initialNameRef.current = personalizationValues.name;
                  }
                }}
              />
            </InputLayouts.Horizontal>
            <InputLayouts.Horizontal
              title="Work Role"
              description="Share your role to better tailor responses."
              center
            >
              <InputTypeIn
                placeholder="Your role"
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
                    void handleSavePersonalization();
                    initialRoleRef.current = personalizationValues.role;
                  }
                }}
              />
            </InputLayouts.Horizontal>
          </Card>
        </Section>

        <Section gap={0.75}>
          <Content
            title="Appearance"
            sizePreset="main-content"
            variant="section"
            widthVariant="full"
          />
          <Card>
            <InputLayouts.Horizontal
              title="Color Mode"
              description="Select your preferred color mode for the UI."
              center
            >
              <InputSelect
                value={theme}
                onValueChange={(value) => {
                  setTheme(value);
                  updateUserThemePreference(value as ThemePreference);
                }}
              >
                <InputSelect.Trigger />
                <InputSelect.Content>
                  <InputSelect.Item
                    value={ThemePreference.SYSTEM}
                    icon={() => (
                      <ColorSwatch
                        light={systemTheme === "light"}
                        dark={systemTheme === "dark"}
                      />
                    )}
                    description={
                      systemTheme
                        ? systemTheme.charAt(0).toUpperCase() +
                          systemTheme.slice(1)
                        : undefined
                    }
                  >
                    Auto
                  </InputSelect.Item>
                  <InputSelect.Separator />
                  <InputSelect.Item
                    value={ThemePreference.LIGHT}
                    icon={() => <ColorSwatch light />}
                  >
                    Light
                  </InputSelect.Item>
                  <InputSelect.Item
                    value={ThemePreference.DARK}
                    icon={() => <ColorSwatch dark />}
                  >
                    Dark
                  </InputSelect.Item>
                </InputSelect.Content>
              </InputSelect>
            </InputLayouts.Horizontal>
            <InputLayouts.Vertical title="Chat Background">
              <div className="flex flex-wrap gap-2">
                {CHAT_BACKGROUND_OPTIONS.map((bg) => {
                  const currentBackgroundId =
                    user?.preferences?.chat_background ?? "none";
                  const isSelected = currentBackgroundId === bg.id;
                  const isNone = bg.src === CHAT_BACKGROUND_NONE;

                  return (
                    <button
                      key={bg.id}
                      onClick={() =>
                        updateUserChatBackground(
                          bg.id === CHAT_BACKGROUND_NONE ? null : bg.id
                        )
                      }
                      className="relative overflow-hidden rounded-lg transition-all w-[90px] h-[68px] cursor-pointer border-none p-0 bg-transparent group"
                      title={bg.label}
                      aria-label={`${bg.label} background${
                        isSelected ? " (selected)" : ""
                      }`}
                    >
                      {isNone ? (
                        <div className="absolute inset-0 bg-background flex items-center justify-center">
                          <span className="text-xs text-text-02">None</span>
                        </div>
                      ) : (
                        <div
                          className="absolute inset-0 bg-cover bg-center transition-transform duration-300 group-hover:scale-105"
                          style={{ backgroundImage: `url(${bg.thumbnail})` }}
                        />
                      )}
                      <div
                        className={cn(
                          "absolute inset-0 transition-all rounded-lg",
                          isSelected
                            ? "ring-2 ring-inset ring-theme-primary-05"
                            : "ring-1 ring-inset ring-border-02 group-hover:ring-border-03"
                        )}
                      />
                      {isSelected && (
                        <div className="absolute top-1.5 right-1.5 w-4 h-4 rounded-full bg-theme-primary-05 flex items-center justify-center">
                          <SvgCheck className="w-2.5 h-2.5 stroke-text-inverted-05" />
                        </div>
                      )}
                    </button>
                  );
                })}
              </div>
            </InputLayouts.Vertical>
          </Card>
        </Section>

        <Separator noPadding />

        <Section gap={0.75}>
          <Content
            title="Danger Zone"
            sizePreset="main-content"
            variant="section"
            widthVariant="full"
          />
          <Card>
            <InputLayouts.Horizontal
              title="Delete All Chats"
              description="Permanently delete all your chat sessions."
              center
            >
              <Button
                danger
                secondary
                onClick={() => setShowDeleteConfirmation(true)}
                leftIcon={SvgTrash}
                transient={showDeleteConfirmation}
              >
                Delete All Chats
              </Button>
            </InputLayouts.Horizontal>
          </Card>
        </Section>
      </Section>
    </>
  );
}

interface LocalShortcut extends InputPrompt {
  isNew: boolean;
}

function PromptShortcuts() {
  const { promptShortcuts, isLoading, error, refresh } = usePromptShortcuts();
  const [shortcuts, setShortcuts] = useState<LocalShortcut[]>([]);
  const [isInitialLoad, setIsInitialLoad] = useState(true);

  // Initialize shortcuts when input prompts are loaded
  useEffect(() => {
    if (isLoading || error) return;

    // Convert InputPrompt[] to LocalShortcut[] with isNew: false for existing items
    // Sort by id to maintain stable ordering when editing
    const existingShortcuts: LocalShortcut[] = promptShortcuts
      .map((shortcut) => ({
        ...shortcut,
        isNew: false,
      }))
      .sort((a, b) => a.id - b.id);

    // Always ensure there's at least one empty row
    setShortcuts([
      ...existingShortcuts,
      {
        id: Date.now(),
        prompt: "",
        content: "",
        active: true,
        is_public: false,
        isNew: true,
      },
    ]);
    setIsInitialLoad(false);
  }, [promptShortcuts, isLoading, error]);

  // Show error popup if fetch fails
  useEffect(() => {
    if (!error) return;
    toast.error("Failed to load shortcuts");
  }, [error]);

  const handleUpdateShortcut = useCallback(
    (index: number, field: "prompt" | "content", value: string) => {
      setShortcuts((prev) => {
        const next = prev.map((shortcut, i) =>
          i === index ? { ...shortcut, [field]: value } : shortcut
        );

        const isEmptyNew = (s: LocalShortcut) =>
          s.isNew && !s.prompt.trim() && !s.content.trim();

        const emptyCount = next.filter(isEmptyNew).length;

        if (emptyCount === 0) {
          return [
            ...next,
            {
              id: Date.now(),
              prompt: "",
              content: "",
              active: true,
              is_public: false,
              isNew: true,
            },
          ];
        }

        if (emptyCount > 1) {
          const userRow = next[index];
          const userRowEmpty = userRow !== undefined && isEmptyNew(userRow);
          let keepIndex = -1;
          if (userRowEmpty) {
            keepIndex = index;
          } else {
            for (let i = next.length - 1; i >= 0; i--) {
              const row = next[i];
              if (row !== undefined && isEmptyNew(row)) {
                keepIndex = i;
                break;
              }
            }
          }
          return next.filter((s, i) => !isEmptyNew(s) || i === keepIndex);
        }

        return next;
      });
    },
    []
  );

  const handleRemoveShortcut = useCallback(
    async (index: number) => {
      const shortcut = shortcuts[index];
      if (!shortcut) return;

      // If it's a new shortcut, just remove from state
      if (shortcut.isNew) {
        setShortcuts((prev) => prev.filter((_, i) => i !== index));
        return;
      }

      // Otherwise, delete from backend
      try {
        const response = await fetch(`/api/input_prompt/${shortcut.id}`, {
          method: "DELETE",
        });

        if (response.ok) {
          setShortcuts((prev) => prev.filter((_, i) => i !== index));
          await refresh();
          toast.success("Shortcut deleted");
        } else {
          throw new Error("Failed to delete shortcut");
        }
      } catch (error) {
        toast.error("Failed to delete shortcut");
      }
    },
    [shortcuts, refresh]
  );

  const handleSaveShortcut = useCallback(
    async (index: number) => {
      const shortcut = shortcuts[index];
      if (!shortcut || !shortcut.prompt.trim() || !shortcut.content.trim()) {
        toast.error("Both shortcut and expansion are required");
        return;
      }

      try {
        if (shortcut.isNew) {
          // Create new shortcut
          const response = await fetch("/api/input_prompt", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              prompt: shortcut.prompt,
              content: shortcut.content,
              active: true,
              is_public: false,
            }),
          });

          if (response.ok) {
            await refresh();
            toast.success("Shortcut created");
          } else {
            throw new Error("Failed to create shortcut");
          }
        } else {
          // Update existing shortcut
          const response = await fetch(`/api/input_prompt/${shortcut.id}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              prompt: shortcut.prompt,
              content: shortcut.content,
              active: true,
              is_public: false,
            }),
          });

          if (response.ok) {
            await refresh();
            toast.success("Shortcut updated");
          } else {
            throw new Error("Failed to update shortcut");
          }
        }
      } catch (error) {
        toast.error("Failed to save shortcut");
      }
    },
    [shortcuts, refresh]
  );

  const handleBlurShortcut = useCallback(
    async (index: number) => {
      const shortcut = shortcuts[index];
      if (!shortcut) return;

      const hasPrompt = shortcut.prompt.trim();
      const hasContent = shortcut.content.trim();

      // Both fields are filled - save/update the shortcut
      if (hasPrompt && hasContent) {
        await handleSaveShortcut(index);
      }
      // For existing shortcuts with incomplete fields, error state will be shown in UI
      // User must use the delete button to remove them
    },
    [shortcuts, handleSaveShortcut]
  );

  return (
    <>
      {shortcuts.length > 0 && (
        <Section gap={0.75}>
          {shortcuts.map((shortcut, index) => {
            const isEmpty = !shortcut.prompt.trim() && !shortcut.content.trim();
            const isExisting = !shortcut.isNew;
            const hasPrompt = shortcut.prompt.trim();
            const hasContent = shortcut.content.trim();

            // Show error for existing shortcuts with incomplete fields
            // (either one field empty or both fields empty)
            const showPromptError = isExisting && !hasPrompt;
            const showContentError = isExisting && !hasContent;

            return (
              <div
                key={shortcut.id}
                className="w-full grid grid-cols-[1fr_min-content] gap-x-1 gap-y-1"
              >
                <InputTypeIn
                  prefixText="/"
                  placeholder="Summarize"
                  value={shortcut.prompt}
                  onChange={(e) =>
                    handleUpdateShortcut(index, "prompt", e.target.value)
                  }
                  onBlur={
                    shortcut.is_public
                      ? undefined
                      : () => void handleBlurShortcut(index)
                  }
                  variant={
                    shortcut.is_public
                      ? "readOnly"
                      : showPromptError
                        ? "error"
                        : undefined
                  }
                />
                <Section>
                  <OpalButton
                    icon={SvgMinusCircle}
                    onClick={() => void handleRemoveShortcut(index)}
                    prominence="tertiary"
                    disabled={(shortcut.isNew && isEmpty) || shortcut.is_public}
                    aria-label="Remove shortcut"
                    tooltip={
                      shortcut.is_public
                        ? "Cannot delete public prompt-shortcuts."
                        : undefined
                    }
                  />
                </Section>
                <InputTextArea
                  placeholder="Provide a concise 1–2 sentence summary of the following:"
                  value={shortcut.content}
                  onChange={(e) =>
                    handleUpdateShortcut(index, "content", e.target.value)
                  }
                  onBlur={
                    shortcut.is_public
                      ? undefined
                      : () => void handleBlurShortcut(index)
                  }
                  variant={
                    shortcut.is_public
                      ? "readOnly"
                      : showContentError
                        ? "error"
                        : undefined
                  }
                  rows={3}
                />
                <div />
              </div>
            );
          })}
        </Section>
      )}
    </>
  );
}

function ChatPreferencesSettings() {
  const {
    user,
    updateUserPersonalization,
    updateUserAutoScroll,
    updateUserShortcuts,
    updateUserDefaultModel,
    updateUserDefaultAppMode,
  } = useUser();
  const isPaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();
  const settings = useSettingsContext();
  const { isSearchModeAvailable: searchUiEnabled } = settings;
  const llmManager = useLlmManager();

  const {
    personalizationValues,
    toggleUseMemories,
    toggleEnableMemoryTool,
    updateUserPreferences,
    handleSavePersonalization,
  } = useUserPersonalization(user, updateUserPersonalization, {
    onSuccess: () => toast.success("Preferences saved"),
    onError: () => toast.error("Failed to save preferences"),
  });

  // Wrapper to save memories and return success/failure
  const handleSaveMemories = useCallback(
    async (newMemories: MemoryItem[]): Promise<boolean> => {
      const result = await handleSavePersonalization(
        { memories: newMemories },
        true
      );
      return !!result;
    },
    [handleSavePersonalization]
  );

  return (
    <Section gap={2}>
      <Section gap={0.75}>
        <Content
          title="Chats"
          sizePreset="main-content"
          variant="section"
          widthVariant="full"
        />
        <Card>
          <InputLayouts.Horizontal
            title="Default Model"
            description="This model will be used by Onyx by default in your chats."
          >
            <LLMPopover
              llmManager={llmManager}
              onSelect={(selected) => {
                void updateUserDefaultModel(selected);
              }}
            />
          </InputLayouts.Horizontal>

          <InputLayouts.Horizontal
            title="Chat Auto-scroll"
            description="Automatically scroll to new content as chat generates response."
          >
            <Switch
              checked={user?.preferences.auto_scroll}
              onCheckedChange={(checked) => {
                updateUserAutoScroll(checked);
              }}
            />
          </InputLayouts.Horizontal>

          {isPaidEnterpriseFeaturesEnabled && (
            <SimpleTooltip
              tooltip={
                searchUiEnabled
                  ? undefined
                  : "Search UI is disabled and can only be enabled by an admin."
              }
              side="top"
            >
              <InputLayouts.Horizontal
                title="Default App Mode"
                description="Choose whether new sessions start in Search or Chat mode."
                center
                disabled={!searchUiEnabled}
              >
                <InputSelect
                  value={user?.preferences.default_app_mode ?? "CHAT"}
                  onValueChange={(value) => {
                    void updateUserDefaultAppMode(value as "CHAT" | "SEARCH");
                  }}
                  disabled={!searchUiEnabled}
                >
                  <InputSelect.Trigger />
                  <InputSelect.Content>
                    <InputSelect.Item value="CHAT">Chat</InputSelect.Item>
                    <InputSelect.Item value="SEARCH">Search</InputSelect.Item>
                  </InputSelect.Content>
                </InputSelect>
              </InputLayouts.Horizontal>
            </SimpleTooltip>
          )}
        </Card>
      </Section>

      <Section gap={0.75}>
        <InputLayouts.Vertical
          title="Personal Preferences"
          description="Provide your custom preferences in natural language."
        >
          <InputTextArea
            placeholder="Describe how you want the system to behave and the tone it should use."
            value={personalizationValues.user_preferences}
            onChange={(e) => updateUserPreferences(e.target.value)}
            onBlur={() => void handleSavePersonalization()}
            rows={4}
            maxRows={10}
            autoResize
            maxLength={500}
          />
          <CharacterCount
            value={personalizationValues.user_preferences || ""}
            limit={500}
          />
        </InputLayouts.Vertical>
        <Content
          title="Memory"
          sizePreset="main-content"
          variant="section"
          widthVariant="full"
        />
        <Card>
          <InputLayouts.Horizontal
            title="Reference Stored Memories"
            description="Let Onyx reference stored memories in chats."
          >
            <Switch
              checked={personalizationValues.use_memories}
              onCheckedChange={(checked) => {
                toggleUseMemories(checked);
                void handleSavePersonalization({ use_memories: checked });
              }}
            />
          </InputLayouts.Horizontal>
          <InputLayouts.Horizontal
            title="Update Memories"
            description="Let Onyx generate and update stored memories."
          >
            <Switch
              checked={personalizationValues.enable_memory_tool}
              onCheckedChange={(checked) => {
                toggleEnableMemoryTool(checked);
                void handleSavePersonalization({
                  enable_memory_tool: checked,
                });
              }}
            />
          </InputLayouts.Horizontal>

          {(personalizationValues.use_memories ||
            personalizationValues.enable_memory_tool ||
            personalizationValues.memories.length > 0) && (
            <Memories
              memories={personalizationValues.memories}
              onSaveMemories={handleSaveMemories}
            />
          )}
        </Card>
      </Section>

      <Section gap={0.75}>
        <Content
          title="Prompt Shortcuts"
          sizePreset="main-content"
          variant="section"
          widthVariant="full"
        />
        <Card>
          <InputLayouts.Horizontal
            title="Use Prompt Shortcuts"
            description="Enable shortcuts to quickly insert common prompts."
          >
            <Switch
              checked={user?.preferences?.shortcut_enabled}
              onCheckedChange={(checked) => {
                updateUserShortcuts(checked);
              }}
            />
          </InputLayouts.Horizontal>

          {user?.preferences?.shortcut_enabled && <PromptShortcuts />}
        </Card>
      </Section>
    </Section>
  );
}

function AccountsAccessSettings() {
  const { user, authTypeMetadata } = useUser();
  const authType = useAuthType();
  const [showPasswordModal, setShowPasswordModal] = useState(false);

  const passwordValidationSchema = Yup.object().shape({
    currentPassword: Yup.string().required("Current password is required"),
    newPassword: Yup.string()
      .min(
        authTypeMetadata.passwordMinLength,
        `Password must be at least ${authTypeMetadata.passwordMinLength} characters`
      )
      .required("New password is required"),
    confirmPassword: Yup.string()
      .oneOf([Yup.ref("newPassword")], "Passwords do not match")
      .required("Please confirm your new password"),
  });

  // PAT state
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [newTokenName, setNewTokenName] = useState("");
  const [expirationDays, setExpirationDays] = useState<string>("30");
  const [newlyCreatedToken, setNewlyCreatedToken] =
    useState<CreatedTokenState | null>(null);
  const [tokenToDelete, setTokenToDelete] = useState<PAT | null>(null);

  const canCreateTokens = useCloudSubscription();

  const showPasswordSection = Boolean(user?.password_configured);
  const showTokensSection = authType !== null;

  // Fetch PATs with SWR
  const {
    data: pats = [],
    mutate,
    error,
    isLoading,
  } = useSWR<PAT[]>(
    showTokensSection ? "/api/user/pats" : null,
    errorHandlingFetcher,
    {
      revalidateOnFocus: true,
      dedupingInterval: 2000,
      fallbackData: [],
    }
  );

  // Use filter hook for searching tokens
  const {
    query,
    setQuery,
    filtered: filteredPats,
  } = useFilter(pats, (pat) => `${pat.name} ${pat.token_display}`);

  // Show error popup if SWR fetch fails
  useEffect(() => {
    if (error) {
      toast.error("Failed to load tokens");
    }
  }, [error]);

  const createPAT = useCallback(async () => {
    if (!newTokenName.trim()) {
      toast.error("Token name is required");
      return;
    }

    setIsCreating(true);
    try {
      const response = await fetch("/api/user/pats", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: newTokenName,
          expiration_days:
            expirationDays === "null" ? null : parseInt(expirationDays),
        }),
      });

      if (response.ok) {
        const data = await response.json();
        // Store the newly created token - modal will switch to display view
        setNewlyCreatedToken({
          id: data.id,
          token: data.token,
          name: newTokenName,
        });
        toast.success("Token created successfully");
        // Revalidate the token list
        await mutate();
      } else {
        const errorData = await response.json();
        toast.error(errorData.detail || "Failed to create token");
      }
    } catch (error) {
      toast.error("Network error creating token");
    } finally {
      setIsCreating(false);
    }
  }, [newTokenName, expirationDays, mutate]);

  const deletePAT = useCallback(
    async (patId: number) => {
      try {
        const response = await fetch(`/api/user/pats/${patId}`, {
          method: "DELETE",
        });

        if (response.ok) {
          // Clear the newly created token if it's the one being deleted
          if (newlyCreatedToken?.id === patId) {
            setNewlyCreatedToken(null);
          }
          await mutate();
          toast.success("Token deleted successfully");
          setTokenToDelete(null);
        } else {
          toast.error("Failed to delete token");
        }
      } catch (error) {
        toast.error("Network error deleting token");
      }
    },
    [newlyCreatedToken, mutate]
  );

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
          toast.success("Password updated successfully");
          setShowPasswordModal(false);
        } else {
          const errorData = await response.json();
          toast.error(errorData.detail || "Failed to change password");
        }
      } catch (error) {
        toast.error("An error occurred while changing the password");
      }
    },
    []
  );

  return (
    <>
      {showCreateModal && (
        <PATModal
          isCreating={isCreating}
          newTokenName={newTokenName}
          setNewTokenName={setNewTokenName}
          expirationDays={expirationDays}
          setExpirationDays={setExpirationDays}
          onClose={() => {
            setShowCreateModal(false);
            setNewTokenName("");
            setExpirationDays("30");
            setNewlyCreatedToken(null);
          }}
          onCreate={createPAT}
          createdToken={newlyCreatedToken}
        />
      )}

      {tokenToDelete && (
        <ConfirmationModalLayout
          icon={SvgTrash}
          title="Revoke Access Token"
          onClose={() => setTokenToDelete(null)}
          submit={
            <Button danger onClick={() => deletePAT(tokenToDelete.id)}>
              Revoke
            </Button>
          }
        >
          <Section gap={0.5} alignItems="start">
            <Text>
              Any application using the token{" "}
              <Text className="!font-bold">{tokenToDelete.name}</Text>{" "}
              <Text secondaryMono>({tokenToDelete.token_display})</Text> will
              lose access to Onyx. This action cannot be undone.
            </Text>
            <Text>Are you sure you want to revoke this token?</Text>
          </Section>
        </ConfirmationModalLayout>
      )}

      {showPasswordModal && (
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
                title="Change Password"
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
                    {isSubmitting ? "Updating..." : "Update"}
                  </Button>
                }
                onClose={() => {
                  setShowPasswordModal(false);
                }}
              >
                <Section gap={1}>
                  <Section gap={0.25} alignItems="start">
                    <InputLayouts.Vertical
                      name="currentPassword"
                      title="Current Password"
                    >
                      <PasswordInputTypeIn
                        name="currentPassword"
                        value={values.currentPassword}
                        onChange={handleChange}
                        onBlur={handleBlur}
                        error={
                          touched.currentPassword && !!errors.currentPassword
                        }
                      />
                    </InputLayouts.Vertical>
                  </Section>
                  <Section gap={0.25} alignItems="start">
                    <InputLayouts.Vertical
                      name="newPassword"
                      title="New Password"
                    >
                      <PasswordInputTypeIn
                        name="newPassword"
                        value={values.newPassword}
                        onChange={handleChange}
                        onBlur={handleBlur}
                        error={touched.newPassword && !!errors.newPassword}
                      />
                    </InputLayouts.Vertical>
                  </Section>
                  <Section gap={0.25} alignItems="start">
                    <InputLayouts.Vertical
                      name="confirmPassword"
                      title="Confirm New Password"
                    >
                      <PasswordInputTypeIn
                        name="confirmPassword"
                        value={values.confirmPassword}
                        onChange={handleChange}
                        onBlur={handleBlur}
                        error={
                          touched.confirmPassword && !!errors.confirmPassword
                        }
                      />
                    </InputLayouts.Vertical>
                  </Section>
                </Section>
              </ConfirmationModalLayout>
            </Form>
          )}
        </Formik>
      )}

      <Section gap={2}>
        <Section gap={0.75}>
          <Content
            title="Accounts"
            sizePreset="main-content"
            variant="section"
            widthVariant="full"
          />
          <Card>
            <InputLayouts.Horizontal
              title="Email"
              description="Your account email address."
              center
              nonInteractive
            >
              <Text>{user?.email ?? "anonymous"}</Text>
            </InputLayouts.Horizontal>

            {showPasswordSection && (
              <InputLayouts.Horizontal
                title="Password"
                description="Update your account password."
                center
              >
                <Button
                  secondary
                  leftIcon={SvgLock}
                  onClick={() => setShowPasswordModal(true)}
                  transient={showPasswordModal}
                >
                  Change Password
                </Button>
              </InputLayouts.Horizontal>
            )}
          </Card>
        </Section>

        {showTokensSection && (
          <Section gap={0.75}>
            <Content
              title="Access Tokens"
              sizePreset="main-content"
              variant="section"
              widthVariant="full"
            />
            {canCreateTokens ? (
              <Card padding={0.25}>
                <Section gap={0}>
                  <Section flexDirection="row" padding={0.25} gap={0.5}>
                    {pats.length === 0 ? (
                      <Section padding={0.5} alignItems="start">
                        <Text text03 secondaryBody>
                          {isLoading
                            ? "Loading tokens..."
                            : "No access tokens created."}
                        </Text>
                      </Section>
                    ) : (
                      <InputTypeIn
                        placeholder="Search..."
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        leftSearchIcon
                        variant="internal"
                      />
                    )}
                    <CreateButton
                      onClick={() => setShowCreateModal(true)}
                      secondary={false}
                      internal
                      transient={showCreateModal}
                      rightIcon
                    >
                      New Access Token
                    </CreateButton>
                  </Section>

                  <Section gap={0.25}>
                    {filteredPats.map((pat) => {
                      const now = new Date();
                      const createdDate = new Date(pat.created_at);
                      const daysSinceCreation = Math.floor(
                        (now.getTime() - createdDate.getTime()) /
                          (1000 * 60 * 60 * 24)
                      );

                      let expiryText = "Never expires";
                      if (pat.expires_at) {
                        const expiresDate = new Date(pat.expires_at);
                        const daysUntilExpiry = Math.ceil(
                          (expiresDate.getTime() - now.getTime()) /
                            (1000 * 60 * 60 * 24)
                        );
                        expiryText = `Expires in ${daysUntilExpiry} day${
                          daysUntilExpiry === 1 ? "" : "s"
                        }`;
                      }

                      const middleText = `Created ${daysSinceCreation} day${
                        daysSinceCreation === 1 ? "" : "s"
                      } ago - ${expiryText}`;

                      return (
                        <Interactive.Container
                          key={pat.id}
                          heightVariant="fit"
                          widthVariant="full"
                        >
                          <div className="w-full bg-background-tint-01">
                            <AttachmentItemLayout
                              icon={SvgKey}
                              title={pat.name}
                              description={pat.token_display}
                              middleText={middleText}
                              rightChildren={
                                <OpalButton
                                  icon={SvgTrash}
                                  onClick={() => setTokenToDelete(pat)}
                                  prominence="tertiary"
                                  size="sm"
                                  aria-label={`Delete token ${pat.name}`}
                                />
                              }
                            />
                          </div>
                        </Interactive.Container>
                      );
                    })}
                  </Section>
                </Section>
              </Card>
            ) : (
              <Card>
                <Section flexDirection="row" justifyContent="between">
                  <Text text03 secondaryBody>
                    Access tokens require an active paid subscription.
                  </Text>
                  <Button secondary href="/admin/billing">
                    Upgrade Plan
                  </Button>
                </Section>
              </Card>
            )}
          </Section>
        )}
      </Section>
    </>
  );
}

interface IndexedConnectorCardProps {
  source: ValidSources;
  isActive: boolean;
}

function IndexedConnectorCard({ source, isActive }: IndexedConnectorCardProps) {
  const sourceMetadata = getSourceMetadata(source);

  return (
    <Card>
      <Content
        icon={sourceMetadata.icon}
        title={sourceMetadata.displayName}
        description={isActive ? "Connected" : "Paused"}
        sizePreset="main-content"
        variant="section"
      />
    </Card>
  );
}

interface FederatedConnectorCardProps {
  connector: FederatedConnectorOAuthStatus;
  onDisconnectSuccess: () => void;
}

function FederatedConnectorCard({
  connector,
  onDisconnectSuccess,
}: FederatedConnectorCardProps) {
  const [isDisconnecting, setIsDisconnecting] = useState(false);
  const [showDisconnectConfirmation, setShowDisconnectConfirmation] =
    useState(false);
  const sourceMetadata = getSourceMetadata(connector.source as ValidSources);

  const handleDisconnect = useCallback(async () => {
    setIsDisconnecting(true);
    try {
      const response = await fetch(
        `/api/federated/${connector.federated_connector_id}/oauth`,
        { method: "DELETE" }
      );

      if (response.ok) {
        toast.success("Disconnected successfully");
        setShowDisconnectConfirmation(false);
        onDisconnectSuccess();
      } else {
        throw new Error("Failed to disconnect");
      }
    } catch (error) {
      toast.error("Failed to disconnect");
    } finally {
      setIsDisconnecting(false);
    }
  }, [connector.federated_connector_id, onDisconnectSuccess]);

  return (
    <>
      {showDisconnectConfirmation && (
        <ConfirmationModalLayout
          icon={SvgUnplug}
          title={`Disconnect ${sourceMetadata.displayName}`}
          onClose={() => setShowDisconnectConfirmation(false)}
          submit={
            <Button
              danger
              onClick={() => void handleDisconnect()}
              disabled={isDisconnecting}
            >
              {isDisconnecting ? "Disconnecting..." : "Disconnect"}
            </Button>
          }
        >
          <Section gap={0.5} alignItems="start">
            <Text>
              Onyx will no longer be able to access or search content from your{" "}
              <Text className="!font-bold">{sourceMetadata.displayName}</Text>{" "}
              account.
            </Text>
            <Text>
              You can still continue existing sessions referencing{" "}
              {sourceMetadata.displayName} content.
            </Text>
          </Section>
        </ConfirmationModalLayout>
      )}

      <Card padding={0.5}>
        <ContentAction
          icon={sourceMetadata.icon}
          title={sourceMetadata.displayName}
          description={
            connector.has_oauth_token ? "Connected" : "Not connected"
          }
          sizePreset="main-content"
          variant="section"
          paddingVariant="sm"
          rightChildren={
            connector.has_oauth_token ? (
              <OpalButton
                icon={SvgUnplug}
                prominence="tertiary"
                size="sm"
                onClick={() => setShowDisconnectConfirmation(true)}
                disabled={isDisconnecting}
              />
            ) : connector.authorize_url ? (
              <Button
                href={connector.authorize_url}
                target="_blank"
                internal
                rightIcon={SvgArrowExchange}
              >
                Connect
              </Button>
            ) : undefined
          }
        />
      </Card>
    </>
  );
}

function ConnectorsSettings() {
  const {
    connectors: federatedConnectors,
    refetch: refetchFederatedConnectors,
  } = useFederatedOAuthStatus();
  const { ccPairs } = useCCPairs();

  const ACTIVE_STATUSES: ConnectorCredentialPairStatus[] = [
    ConnectorCredentialPairStatus.ACTIVE,
    ConnectorCredentialPairStatus.SCHEDULED,
    ConnectorCredentialPairStatus.INITIAL_INDEXING,
  ];

  // Group indexed connectors by source
  const groupedConnectors = ccPairs.reduce(
    (acc, ccPair) => {
      if (!acc[ccPair.source]) {
        acc[ccPair.source] = {
          source: ccPair.source,
          hasActiveConnector: false,
        };
      }
      if (ACTIVE_STATUSES.includes(ccPair.status)) {
        acc[ccPair.source]!.hasActiveConnector = true;
      }
      return acc;
    },
    {} as Record<
      string,
      {
        source: ValidSources;
        hasActiveConnector: boolean;
      }
    >
  );

  const hasConnectors =
    Object.keys(groupedConnectors).length > 0 || federatedConnectors.length > 0;

  return (
    <Section gap={2}>
      <Section gap={0.75} justifyContent="start">
        <Content
          title="Connectors"
          sizePreset="main-content"
          variant="section"
          widthVariant="full"
        />
        {hasConnectors ? (
          <>
            {/* Indexed Connectors */}
            {Object.values(groupedConnectors).map((connector) => (
              <IndexedConnectorCard
                key={connector.source}
                source={connector.source}
                isActive={connector.hasActiveConnector}
              />
            ))}

            {/* Federated Connectors */}
            {federatedConnectors.map((connector) => (
              <FederatedConnectorCard
                key={connector.federated_connector_id}
                connector={connector}
                onDisconnectSuccess={() => refetchFederatedConnectors?.()}
              />
            ))}
          </>
        ) : (
          <EmptyMessage title="No connectors set up for your organization." />
        )}
      </Section>
    </Section>
  );
}

export {
  GeneralSettings,
  ChatPreferencesSettings,
  AccountsAccessSettings,
  ConnectorsSettings,
};
