"use client";

import { useRef, useCallback, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import type { Route } from "next";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import * as InputLayouts from "@/layouts/input-layouts";
import * as GeneralLayouts from "@/layouts/general-layouts";
import SidebarTab from "@/refresh-components/buttons/SidebarTab";
import { Formik, Form } from "formik";
import {
  SvgExternalLink,
  SvgKey,
  SvgLock,
  SvgMinusCircle,
  SvgSliders,
  SvgTrash,
} from "@opal/icons";
import Card from "@/refresh-components/cards/Card";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";
import Button from "@/refresh-components/buttons/Button";
import Switch from "@/refresh-components/inputs/Switch";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { useUser } from "@/components/user/UserProvider";
import { useTheme } from "next-themes";
import { ThemePreference } from "@/lib/types";
import useUserPersonalization from "@/hooks/useUserPersonalization";
import { usePopup } from "@/components/admin/connectors/Popup";
import LLMPopover from "@/refresh-components/popovers/LLMPopover";
import { deleteAllChatSessions } from "@/app/chat/services/lib";
import { useAuthType, useLlmManager } from "@/lib/hooks";
import { AuthType } from "@/lib/constants";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { humanReadableFormat } from "@/lib/time";
import useFilter from "@/hooks/useFilter";
import CreateButton from "@/refresh-components/buttons/CreateButton";
import IconButton from "@/refresh-components/buttons/IconButton";
import { useFederatedOAuthStatus } from "@/lib/hooks/useFederatedOAuthStatus";
import { useCCPairs } from "@/lib/hooks/useCCPairs";
import { SourceIcon } from "@/components/SourceIcon";
import { ValidSources } from "@/lib/types";
import { getSourceMetadata } from "@/lib/sources";
import Separator from "@/refresh-components/Separator";
import Text from "@/refresh-components/texts/Text";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import Code from "@/refresh-components/Code";
import { InputPrompt } from "@/app/chat/interfaces";
import { useInputPrompts } from "@/hooks/useInputPrompts";
import ColorSwatch from "@/refresh-components/ColorSwatch";
import AttachmentButton from "@/refresh-components/buttons/AttachmentButton";

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
      <GeneralLayouts.Section gap={1}>
        {/* Token Creation*/}
        {!!createdToken?.token ? (
          <InputLayouts.Vertical label="Token Value">
            <Code>{createdToken.token}</Code>
          </InputLayouts.Vertical>
        ) : (
          <>
            <InputLayouts.Vertical label="Token Name">
              <InputTypeIn
                placeholder="Name your token"
                value={newTokenName}
                onChange={(e) => setNewTokenName(e.target.value)}
                disabled={isCreating}
                autoComplete="new-password"
              />
            </InputLayouts.Vertical>
            <InputLayouts.Vertical
              label="Expires in"
              description="Expires at end of day (23:59 UTC)."
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
      </GeneralLayouts.Section>
    </ConfirmationModalLayout>
  );
}

function GeneralSettings() {
  const { user, updateUserPersonalization, updateUserThemePreference } =
    useUser();
  const { theme, setTheme, resolvedTheme } = useTheme();
  const { popup, setPopup } = usePopup();
  const router = useRouter();
  const pathname = usePathname();
  const [isDeleting, setIsDeleting] = useState(false);
  const [showDeleteConfirmation, setShowDeleteConfirmation] = useState(false);

  const {
    personalizationValues,
    updatePersonalizationField,
    handleSavePersonalization,
    isSavingPersonalization,
  } = useUserPersonalization(user, updateUserPersonalization, {
    onSuccess: () =>
      setPopup({
        message: "Personalization updated successfully",
        type: "success",
      }),
    onError: () =>
      setPopup({
        message: "Failed to update personalization",
        type: "error",
      }),
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
        setPopup({
          message: "All your chat sessions have been deleted.",
          type: "success",
        });
        if (pathname.includes("/chat")) {
          router.push("/chat");
        }
      } else {
        throw new Error("Failed to delete all chat sessions");
      }
    } catch (error) {
      setPopup({
        message: "Failed to delete all chat sessions",
        type: "error",
      });
    } finally {
      setIsDeleting(false);
      setShowDeleteConfirmation(false);
    }
  }, [pathname, router, setPopup]);

  return (
    <>
      {popup}

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
          <GeneralLayouts.Section gap={0.5} start>
            <Text>
              All your chat sessions and history will be permanently deleted.
              Deletion cannot be undone.
            </Text>
            <Text>Are you sure you want to delete all chats?</Text>
          </GeneralLayouts.Section>
        </ConfirmationModalLayout>
      )}

      <GeneralLayouts.Section gap={2}>
        <GeneralLayouts.Section gap={0.75}>
          <InputLayouts.Label label="Profile" />
          <Card>
            <InputLayouts.Horizontal
              label="Full Name"
              description="We'll display this name in the app."
              center
            >
              <InputTypeIn
                placeholder="Your name"
                value={personalizationValues.name}
                onChange={(e) =>
                  updatePersonalizationField("name", e.target.value)
                }
                onBlur={() => {
                  // Only save if the value has changed and is not empty
                  if (
                    personalizationValues.name.trim() &&
                    personalizationValues.name !== initialNameRef.current
                  ) {
                    void handleSavePersonalization();
                    initialNameRef.current = personalizationValues.name;
                  }
                }}
              />
            </InputLayouts.Horizontal>
            <InputLayouts.Horizontal
              label="Work Role"
              description="Share your role to better tailor responses."
              center
            >
              <InputTypeIn
                placeholder="Your role"
                value={personalizationValues.role}
                onChange={(e) =>
                  updatePersonalizationField("role", e.target.value)
                }
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
        </GeneralLayouts.Section>

        <GeneralLayouts.Section gap={0.75}>
          <InputLayouts.Label label="Appearance" />
          <Card>
            <InputLayouts.Horizontal
              label="Color Mode"
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
                        light={resolvedTheme === "light"}
                        dark={resolvedTheme === "dark"}
                      />
                    )}
                    description={
                      resolvedTheme
                        ? resolvedTheme.charAt(0).toUpperCase() +
                          resolvedTheme.slice(1)
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
          </Card>
        </GeneralLayouts.Section>

        <Separator noPadding />

        <GeneralLayouts.Section gap={0.75}>
          <InputLayouts.Label label="Danger Zone" />
          <Card>
            <InputLayouts.Horizontal
              label="Delete All Chats"
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
        </GeneralLayouts.Section>
      </GeneralLayouts.Section>
    </>
  );
}

function PromptShortcuts() {
  const { popup, setPopup } = usePopup();
  const { inputPrompts, isLoading, error, refetch } = useInputPrompts();

  const [shortcuts, setShortcuts] = useState<InputPrompt[]>([]);
  const [isInitialLoad, setIsInitialLoad] = useState(true);

  // Initialize shortcuts when input prompts are loaded
  useEffect(() => {
    if (isLoading || error) return;

    // Always ensure there's at least one empty row
    setShortcuts([
      ...inputPrompts,
      {
        id: -Date.now(),
        prompt: "",
        content: "",
        active: true,
        is_public: false,
      },
    ]);
    setIsInitialLoad(false);
  }, [inputPrompts, isLoading, error]);

  // Show error popup if fetch fails
  useEffect(() => {
    if (!error) return;
    setPopup({ message: "Failed to load shortcuts", type: "error" });
  }, [error, setPopup]);

  // Auto-add empty row when user starts typing in the last row
  useEffect(() => {
    // Skip during initial load - the fetch useEffect handles the initial empty row
    if (isInitialLoad) return;

    // Only manage new/unsaved rows (negative IDs) - never touch existing shortcuts
    const newShortcuts = shortcuts.filter((s) => s.id < 0);
    const emptyNewRows = newShortcuts.filter(
      (s) => !s.prompt.trim() && !s.content.trim()
    );
    const emptyNewRowsCount = emptyNewRows.length;

    // If we have no empty new rows, add one
    if (emptyNewRowsCount === 0) {
      setShortcuts((prev) => [
        ...prev,
        {
          id: -Date.now(),
          prompt: "",
          content: "",
          active: true,
          is_public: false,
        },
      ]);
    }
    // If we have more than one empty new row, keep only one
    else if (emptyNewRowsCount > 1) {
      setShortcuts((prev) => {
        // Keep all existing shortcuts (id > 0) regardless of their state
        // Keep all new shortcuts that have at least one field filled
        // Add one empty new shortcut
        const existingShortcuts = prev.filter((s) => s.id > 0);
        const filledNewShortcuts = prev.filter(
          (s) => s.id < 0 && (s.prompt.trim() || s.content.trim())
        );
        return [
          ...existingShortcuts,
          ...filledNewShortcuts,
          {
            id: -Date.now(),
            prompt: "",
            content: "",
            active: true,
            is_public: false,
          },
        ];
      });
    }
  }, [shortcuts, isInitialLoad]);

  const handleUpdateShortcut = useCallback(
    (index: number, field: "prompt" | "content", value: string) => {
      setShortcuts((prev) =>
        prev.map((shortcut, i) =>
          i === index ? { ...shortcut, [field]: value } : shortcut
        )
      );
    },
    []
  );

  const handleRemoveShortcut = useCallback(
    async (index: number) => {
      const shortcut = shortcuts[index];
      if (!shortcut) return;

      // If it's a new shortcut (negative ID), just remove from state
      if (shortcut.id < 0) {
        setShortcuts((prev) => prev.filter((_, i) => i !== index));
        return;
      }

      // Otherwise, delete from backend
      try {
        const response = await fetch(`/api/input_prompt/${shortcut.id}`, {
          method: "DELETE",
        });

        if (response.ok) {
          await refetch();
          setPopup({ message: "Shortcut deleted", type: "success" });
        } else {
          throw new Error("Failed to delete shortcut");
        }
      } catch (error) {
        setPopup({ message: "Failed to delete shortcut", type: "error" });
      }
    },
    [shortcuts, setPopup, refetch]
  );

  const handleSaveShortcut = useCallback(
    async (index: number) => {
      const shortcut = shortcuts[index];
      if (!shortcut || !shortcut.prompt.trim() || !shortcut.content.trim()) {
        setPopup({
          message: "Both shortcut and expansion are required",
          type: "error",
        });
        return;
      }

      try {
        if (shortcut.id < 0) {
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
            await refetch();
            setPopup({ message: "Shortcut created", type: "success" });
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
            await refetch();
            setPopup({ message: "Shortcut updated", type: "success" });
          } else {
            throw new Error("Failed to update shortcut");
          }
        }
      } catch (error) {
        setPopup({
          message: "Failed to save shortcut",
          type: "error",
        });
      }
    },
    [shortcuts, setPopup, refetch]
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
      {popup}

      {shortcuts.map((shortcut, index) => {
        const isEmpty = !shortcut.prompt.trim() && !shortcut.content.trim();
        const isExisting = shortcut.id > 0;
        const hasPrompt = shortcut.prompt.trim();
        const hasContent = shortcut.content.trim();

        // Show error for existing shortcuts with incomplete fields
        // (either one field empty or both fields empty)
        const showPromptError = isExisting && !hasPrompt;
        const showContentError = isExisting && !hasContent;

        return (
          <div key={shortcut.id}>
            <GeneralLayouts.Section horizontal gap={0.25}>
              <div className="w-[60%]">
                <InputTypeIn
                  placeholder="/Shortcut"
                  value={shortcut.prompt}
                  onChange={(e) =>
                    handleUpdateShortcut(index, "prompt", e.target.value)
                  }
                  onBlur={() => void handleBlurShortcut(index)}
                  error={showPromptError}
                />
              </div>
              <InputTypeIn
                placeholder="Full prompt"
                value={shortcut.content}
                onChange={(e) =>
                  handleUpdateShortcut(index, "content", e.target.value)
                }
                onBlur={() => void handleBlurShortcut(index)}
                error={showContentError}
              />
              <IconButton
                icon={SvgMinusCircle}
                onClick={() => void handleRemoveShortcut(index)}
                tertiary
                disabled={isEmpty && !isExisting}
                aria-label="Remove shortcut"
              />
            </GeneralLayouts.Section>
          </div>
        );
      })}
    </>
  );
}

function ChatPreferencesSettings() {
  const {
    user,
    updateUserTemperatureOverrideEnabled,
    updateUserPersonalization,
    updateUserAutoScroll,
    updateUserShortcuts,
  } = useUser();
  const { popup, setPopup } = usePopup();
  const llmManager = useLlmManager();

  const {
    personalizationValues,
    toggleUseMemories,
    updateMemoryAtIndex,
    addMemory,
    handleSavePersonalization,
    isSavingPersonalization,
  } = useUserPersonalization(user, updateUserPersonalization, {
    onSuccess: () =>
      setPopup({
        message: "Personalization updated successfully",
        type: "success",
      }),
    onError: () =>
      setPopup({
        message: "Failed to update personalization",
        type: "error",
      }),
  });

  return (
    <>
      {popup}

      <GeneralLayouts.Section gap={2}>
        <GeneralLayouts.Section gap={0.75}>
          <InputLayouts.Label label="Chats" />
          <Card>
            <InputLayouts.Horizontal
              label="Default Model"
              description="This model will be used by Onyx by default in your chats."
            >
              <LLMPopover
                llmManager={llmManager}
                // TODO (@raunakab)
                // Update saving default model.
                //
                // onSelect={(selected) => {
                //   if (selected === null) {
                //     void handleChangeDefaultModel(null);
                //   } else {
                //     const { modelName, provider, name } =
                //       parseLlmDescriptor(selected);
                //     if (modelName && name) {
                //       void handleChangeDefaultModel(
                //         structureValue(name, provider, modelName)
                //       );
                //     }
                //   }
                // }}
              />
            </InputLayouts.Horizontal>

            <InputLayouts.Horizontal
              label="Chat Auto-scroll"
              description="Automatically scroll to new content as chat generates response."
            >
              <Switch
                checked={user?.preferences.auto_scroll}
                onCheckedChange={(checked) => {
                  updateUserAutoScroll(checked);
                }}
              />
            </InputLayouts.Horizontal>

            <InputLayouts.Horizontal
              label="Temperature override"
              description="Set the temperature for the LLM."
            >
              <Switch
                checked={user?.preferences.temperature_override_enabled}
                onCheckedChange={(checked) => {
                  updateUserTemperatureOverrideEnabled(checked);
                }}
              />
            </InputLayouts.Horizontal>
          </Card>
        </GeneralLayouts.Section>

        <GeneralLayouts.Section gap={0.75}>
          <InputLayouts.Label label="Prompt Shortcuts" />
          <Card>
            <InputLayouts.Horizontal
              label="Use Prompt Shortcuts"
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
        </GeneralLayouts.Section>

        <GeneralLayouts.Section gap={0.75}>
          <InputLayouts.Label label="Personalization" />
          <Card>
            <InputLayouts.Horizontal
              label="Reference Stored Memories"
              description="Let Onyx reference stored memories in chats."
            >
              <Switch
                checked={personalizationValues.use_memories}
                onCheckedChange={(checked) => toggleUseMemories(checked)}
              />
            </InputLayouts.Horizontal>

            <div className="space-y-3">
              {personalizationValues.memories.map((memory, index) => (
                <InputTextArea
                  key={index}
                  value={memory}
                  placeholder="Write something Onyx should remember"
                  onChange={(event) =>
                    updateMemoryAtIndex(index, event.target.value)
                  }
                />
              ))}
              <Button tertiary onClick={addMemory} className="w-full">
                Add Memory
              </Button>
            </div>
          </Card>
        </GeneralLayouts.Section>
      </GeneralLayouts.Section>
    </>
  );
}

function AccountsAccessSettings() {
  const { user } = useUser();
  const { popup, setPopup } = usePopup();
  const authType = useAuthType();
  const [showPasswordModal, setShowPasswordModal] = useState(false);

  // PAT state
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [newTokenName, setNewTokenName] = useState("");
  const [expirationDays, setExpirationDays] = useState<string>("30");
  const [newlyCreatedToken, setNewlyCreatedToken] =
    useState<CreatedTokenState | null>(null);
  const [tokenToDelete, setTokenToDelete] = useState<{
    id: number;
    name: string;
  } | null>(null);

  const showPasswordSection = Boolean(user?.password_configured);
  const showTokensSection = authType && authType !== AuthType.DISABLED;

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
      setPopup({ message: "Failed to load tokens", type: "error" });
    }
  }, [error, setPopup]);

  const createPAT = useCallback(async () => {
    if (!newTokenName.trim()) {
      setPopup({ message: "Token name is required", type: "error" });
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
        setPopup({ message: "Token created successfully", type: "success" });
        // Revalidate the token list
        await mutate();
      } else {
        const errorData = await response.json();
        setPopup({
          message: errorData.detail || "Failed to create token",
          type: "error",
        });
      }
    } catch (error) {
      setPopup({ message: "Network error creating token", type: "error" });
    } finally {
      setIsCreating(false);
    }
  }, [newTokenName, expirationDays, mutate, setPopup]);

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
          setPopup({ message: "Token deleted successfully", type: "success" });
        } else {
          setPopup({ message: "Failed to delete token", type: "error" });
        }
      } catch (error) {
        setPopup({ message: "Network error deleting token", type: "error" });
      } finally {
        setTokenToDelete(null);
      }
    },
    [newlyCreatedToken, mutate, setPopup]
  );

  const handleChangePassword = useCallback(
    async (values: {
      currentPassword: string;
      newPassword: string;
      confirmPassword: string;
    }) => {
      if (values.newPassword !== values.confirmPassword) {
        setPopup({ message: "New passwords do not match", type: "error" });
        return;
      }

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
          setPopup({
            message: "Password changed successfully",
            type: "success",
          });
          setShowPasswordModal(false);
        } else {
          const errorData = await response.json();
          setPopup({
            message: errorData.detail || "Failed to change password",
            type: "error",
          });
        }
      } catch (error) {
        setPopup({
          message: "An error occurred while changing the password",
          type: "error",
        });
      }
    },
    [setPopup]
  );

  if (!showPasswordSection && !showTokensSection) {
    return (
      <div className="text-center py-8">
        <p className="text-sm text-muted-foreground">
          No account settings available.
        </p>
      </div>
    );
  }

  return (
    <>
      {popup}

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
          <GeneralLayouts.Section gap={0.5} start>
            <Text>
              Any application using this token will lose access to Onyx. This
              action cannot be undone.
            </Text>
            <Text>Are you sure you want to revoke this token?</Text>
          </GeneralLayouts.Section>
        </ConfirmationModalLayout>
      )}

      {showPasswordModal && (
        <Formik
          initialValues={{
            currentPassword: "",
            newPassword: "",
            confirmPassword: "",
          }}
          onSubmit={async (values, { setSubmitting }) => {
            await handleChangePassword(values);
            setSubmitting(false);
          }}
        >
          {({ values, handleChange, isSubmitting, dirty }) => (
            <Form>
              <ConfirmationModalLayout
                icon={SvgLock}
                title="Change Password"
                submit={
                  <Button
                    type="submit"
                    disabled={
                      isSubmitting ||
                      !dirty ||
                      !values.currentPassword ||
                      !values.newPassword ||
                      !values.confirmPassword
                    }
                  >
                    {isSubmitting ? "Updating..." : "Update"}
                  </Button>
                }
                onClose={() => {
                  setShowPasswordModal(false);
                }}
              >
                <GeneralLayouts.Section gap={1}>
                  <InputLayouts.Vertical label="Current Password">
                    <InputTypeIn
                      name="currentPassword"
                      type="password"
                      value={values.currentPassword}
                      onChange={handleChange}
                    />
                  </InputLayouts.Vertical>
                  <InputLayouts.Vertical label="New Password">
                    <InputTypeIn
                      name="newPassword"
                      type="password"
                      value={values.newPassword}
                      onChange={handleChange}
                    />
                  </InputLayouts.Vertical>
                  <InputLayouts.Vertical label="Confirm New Password">
                    <InputTypeIn
                      name="confirmPassword"
                      type="password"
                      value={values.confirmPassword}
                      onChange={handleChange}
                    />
                  </InputLayouts.Vertical>
                </GeneralLayouts.Section>
              </ConfirmationModalLayout>
            </Form>
          )}
        </Formik>
      )}

      <GeneralLayouts.Section gap={2}>
        <GeneralLayouts.Section gap={0.75}>
          <InputLayouts.Label label="Accounts" />
          <Card>
            <InputLayouts.Horizontal
              label="Email"
              description="Your account email address."
              center
            >
              <Text>{user?.email ?? "anonymous"}</Text>
            </InputLayouts.Horizontal>

            {showPasswordSection && (
              <InputLayouts.Horizontal
                label="Password"
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
        </GeneralLayouts.Section>

        {showTokensSection && (
          <GeneralLayouts.Section gap={0.75}>
            <InputLayouts.Label label="Access Tokens" />
            <Card padding={0.25}>
              <GeneralLayouts.Section gap={0}>
                {/* Header with search/empty state and create button */}
                <GeneralLayouts.Section horizontal padding={0.25} gap={0.5}>
                  {pats.length === 0 ? (
                    <Text as="span" text03 secondaryBody className="flex-1">
                      {isLoading
                        ? "Loading tokens..."
                        : "No access tokens created."}
                    </Text>
                  ) : (
                    <InputTypeIn
                      placeholder="Search..."
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                      leftSearchIcon
                      internal
                    />
                  )}
                  <CreateButton
                    onClick={() => setShowCreateModal(true)}
                    secondary={false}
                    internal
                    transient={showCreateModal}
                  >
                    New Access Token
                  </CreateButton>
                </GeneralLayouts.Section>

                {/* Token List */}
                {filteredPats.map((pat) => (
                  <AttachmentButton
                    key={pat.id}
                    leftIcon={SvgKey}
                    description={pat.token_display}
                    rightText={humanReadableFormat(pat.created_at)}
                    onDelete={() =>
                      setTokenToDelete({ id: pat.id, name: pat.name })
                    }
                  >
                    {pat.name}
                  </AttachmentButton>
                ))}
              </GeneralLayouts.Section>
            </Card>
          </GeneralLayouts.Section>
        )}
      </GeneralLayouts.Section>
    </>
  );
}

function ConnectorsSettings() {
  const { popup, setPopup } = usePopup();
  const router = useRouter();
  const [isDisconnecting, setIsDisconnecting] = useState<number | null>(null);

  const {
    connectors: federatedConnectors,
    refetch: refetchFederatedConnectors,
    loading: isFederatedLoading,
  } = useFederatedOAuthStatus();

  const { ccPairs, isLoading: isCCPairsLoading } = useCCPairs();

  const hasConnectors =
    (ccPairs && ccPairs.length > 0) ||
    (federatedConnectors && federatedConnectors.length > 0);

  const isLoadingConnectors = isCCPairsLoading || isFederatedLoading;

  const handleConnectOAuth = useCallback(
    (authorizeUrl: string) => {
      router.push(authorizeUrl as Route);
    },
    [router]
  );

  const handleDisconnectOAuth = useCallback(
    async (connectorId: number) => {
      setIsDisconnecting(connectorId);
      try {
        const response = await fetch(`/api/federated/${connectorId}/oauth`, {
          method: "DELETE",
        });

        if (response.ok) {
          setPopup({
            message: "Disconnected successfully",
            type: "success",
          });
          if (refetchFederatedConnectors) {
            refetchFederatedConnectors();
          }
        } else {
          throw new Error("Failed to disconnect");
        }
      } catch (error) {
        setPopup({
          message: "Failed to disconnect",
          type: "error",
        });
      } finally {
        setIsDisconnecting(null);
      }
    },
    [refetchFederatedConnectors, setPopup]
  );

  const formatSourceName = (source: string) => {
    return source
      .split("_")
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(" ");
  };

  if (isLoadingConnectors) {
    return (
      <div className="flex items-center justify-center py-8">
        <SimpleLoader />
      </div>
    );
  }

  return (
    <>
      {popup}
      <GeneralLayouts.Section gap={2}>
        <GeneralLayouts.Section gap={0.75}>
          <InputLayouts.Label label="Data Sources" />
          <Card>
            <div>
              <h3 className="text-lg font-medium mb-4">Connected Services</h3>
              <p className="text-sm text-muted-foreground mb-4">
                Manage your connected services to search across all your
                content.
              </p>

              {/* Indexed Connectors Section */}
              {ccPairs && ccPairs.length > 0 && (
                <div className="space-y-3 mb-6">
                  <h4 className="text-md font-medium text-muted-foreground">
                    Indexed Connectors
                  </h4>
                  {(() => {
                    const groupedConnectors = ccPairs.reduce(
                      (acc, ccPair) => {
                        const source = ccPair.source;
                        if (!acc[source]) {
                          acc[source] = {
                            source,
                            count: 0,
                            hasSuccessfulRun: false,
                          };
                        }
                        acc[source]!.count++;
                        if (ccPair.has_successful_run) {
                          acc[source]!.hasSuccessfulRun = true;
                        }
                        return acc;
                      },
                      {} as Record<
                        string,
                        {
                          source: ValidSources;
                          count: number;
                          hasSuccessfulRun: boolean;
                        }
                      >
                    );

                    return Object.values(groupedConnectors).map((group) => (
                      <div
                        key={group.source}
                        className="flex items-center justify-between p-4 rounded-lg border border-border bg-muted/30"
                      >
                        <div className="flex items-center gap-3">
                          <SourceIcon sourceType={group.source} iconSize={24} />
                          <div>
                            <p className="font-medium">
                              {formatSourceName(group.source)}
                            </p>
                            <p className="text-sm text-muted-foreground">
                              {group.count > 1
                                ? `${group.count} connectors`
                                : "Connected"}
                            </p>
                          </div>
                        </div>
                        <div className="text-sm text-muted-foreground font-medium">
                          Active
                        </div>
                      </div>
                    ));
                  })()}
                </div>
              )}

              {/* Federated Search Section */}
              {federatedConnectors && federatedConnectors.length > 0 && (
                <div className="space-y-3">
                  <h4 className="text-md font-medium text-muted-foreground">
                    Federated Connectors
                  </h4>
                  {federatedConnectors.map((connector) => {
                    const sourceMetadata = getSourceMetadata(
                      connector.source as ValidSources
                    );
                    return (
                      <div
                        key={connector.federated_connector_id}
                        className="flex items-center justify-between p-4 rounded-lg border border-border"
                      >
                        <div className="flex items-center gap-3">
                          <SourceIcon
                            sourceType={sourceMetadata.internalName}
                            iconSize={24}
                          />
                          <div>
                            <p className="font-medium">
                              {formatSourceName(sourceMetadata.displayName)}
                            </p>
                            <p className="text-sm text-muted-foreground">
                              {connector.has_oauth_token
                                ? "Connected"
                                : "Not connected"}
                            </p>
                          </div>
                        </div>
                        <div>
                          {connector.has_oauth_token ? (
                            <Button
                              secondary
                              onClick={() =>
                                void handleDisconnectOAuth(
                                  connector.federated_connector_id
                                )
                              }
                              disabled={
                                isDisconnecting ===
                                connector.federated_connector_id
                              }
                            >
                              {isDisconnecting ===
                              connector.federated_connector_id
                                ? "Disconnecting..."
                                : "Disconnect"}
                            </Button>
                          ) : (
                            <Button
                              onClick={() => {
                                if (connector.authorize_url) {
                                  handleConnectOAuth(connector.authorize_url);
                                }
                              }}
                              disabled={!connector.authorize_url}
                              leftIcon={SvgExternalLink}
                            >
                              Connect
                            </Button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}

              {!hasConnectors && (
                <div className="text-center py-8">
                  <p className="text-sm text-muted-foreground">
                    No connectors available.
                  </p>
                </div>
              )}
            </div>
          </Card>
        </GeneralLayouts.Section>
      </GeneralLayouts.Section>
    </>
  );
}

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState(0);
  const { user } = useUser();
  const authType = useAuthType();

  const showPasswordSection = Boolean(user?.password_configured);
  const showTokensSection = authType && authType !== AuthType.DISABLED;
  const showAccountsAccessTab = showPasswordSection || showTokensSection;

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header icon={SvgSliders} title="Settings" separator />

      <SettingsLayouts.Body>
        <div className="grid grid-cols-[auto_1fr]">
          {/* Left: Tab Navigation */}
          <div className="flex flex-col px-2 w-[12.5rem]">
            <SidebarTab
              transient={activeTab === 0}
              onClick={() => setActiveTab(0)}
            >
              General
            </SidebarTab>
            <SidebarTab
              transient={activeTab === 1}
              onClick={() => setActiveTab(1)}
            >
              Chat Preferences
            </SidebarTab>
            {showAccountsAccessTab && (
              <SidebarTab
                transient={activeTab === 2}
                onClick={() => setActiveTab(2)}
              >
                Accounts & Access
              </SidebarTab>
            )}
            <SidebarTab
              transient={activeTab === 3}
              onClick={() => setActiveTab(3)}
            >
              Connectors
            </SidebarTab>
          </div>

          {/* Right: Tab Content */}
          <div className="px-4">
            {activeTab === 0 && <GeneralSettings />}
            {activeTab === 1 && <ChatPreferencesSettings />}
            {activeTab === 2 && showAccountsAccessTab && (
              <AccountsAccessSettings />
            )}
            {activeTab === 3 && <ConnectorsSettings />}
          </div>
        </div>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
