"use client";

import { useRef, useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Section, AttachmentItemLayout } from "@/layouts/general-layouts";
import {
  Content,
  ContentAction,
  InputHorizontal,
  InputVertical,
} from "@opal/layouts";
import { markdown } from "@opal/utils";
import { Formik, Form } from "formik";
import * as Yup from "yup";
import {
  SvgArrowExchange,
  SvgKey,
  SvgLock,
  SvgMinusCircle,
  SvgPlusCircle,
  SvgTrash,
  SvgUnplug,
} from "@opal/icons";
import { getSourceMetadata } from "@/lib/sources";
import Card from "@/refresh-components/cards/Card";
import { InputTypeIn } from "@opal/components";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";
import { Switch } from "@opal/components";
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
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";
import useFilter from "@/hooks/useFilter";
import { Button, Divider, Checkbox, Text } from "@opal/components";
import useFederatedOAuthStatus from "@/hooks/useFederatedOAuthStatus";
import useCCPairs from "@/hooks/useCCPairs";
import { ValidSources } from "@/lib/types";
import { ConnectorCredentialPairStatus } from "@/app/admin/connector/[ccPairId]/types";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import Modal, { BasicModalFooter } from "@/refresh-components/Modal";
import { Code, CopyButton } from "@opal/components";
import CharacterCount from "@/refresh-components/CharacterCount";
import { InputPrompt } from "@/app/app/interfaces";
import usePromptShortcuts from "@/hooks/usePromptShortcuts";
import ColorSwatch from "@/refresh-components/ColorSwatch";
import { EmptyMessageCard } from "@opal/components";
import Memories from "@/sections/settings/Memories";
import { FederatedConnectorOAuthStatus } from "@/components/chat/FederatedOAuthModal";
import {
  CHAT_BACKGROUND_OPTIONS,
  CHAT_BACKGROUND_NONE,
} from "@/lib/constants/chatBackgrounds";
import { SvgCheck } from "@opal/icons";
import { cn } from "@opal/utils";
import { Interactive } from "@opal/core";
import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { Tier } from "@/interfaces/settings";
import { useSettingsContext } from "@/providers/SettingsProvider";
import { Tooltip } from "@opal/components";
import { useCloudSubscription } from "@/hooks/useCloudSubscription";
import { useSmoothStreaming } from "@/hooks/useSmoothStreaming";

interface PAT {
  id: number;
  name: string;
  token_display: string;
  created_at: string;
  expires_at: string | null;
  last_used_at: string | null;
  scopes: string[] | null;
}

interface PatScopeOption {
  scope: string;
  group_label: string;
  label: string;
  description: string;
  implies: string[];
}

type AccessMode = "full" | "limited";

interface CreatedTokenState {
  id: number;
  token: string;
  name: string;
}

interface ScopeGroup {
  label: string;
  rows: PatScopeOption[];
}

interface ScopeSelectorProps {
  scopeOptions: PatScopeOption[];
  selectedScopes: string[];
  toggleScope: (scope: string) => void;
  scopesError: boolean;
  disabled: boolean;
}

// Data-driven from the /scopes payload, so new scopes need no change here.
function ScopeSelector({
  scopeOptions,
  selectedScopes,
  toggleScope,
  scopesError,
  disabled,
}: ScopeSelectorProps) {
  const groups = useMemo(() => {
    const byLabel = new Map<string, ScopeGroup>();
    for (const option of scopeOptions) {
      const group = byLabel.get(option.group_label);
      if (group) {
        group.rows.push(option);
      } else {
        byLabel.set(option.group_label, {
          label: option.group_label,
          rows: [option],
        });
      }
    }
    return Array.from(byLabel.values());
  }, [scopeOptions]);

  if (scopesError) {
    return (
      <Text font="secondary-body" color="text-03">
        权限加载失败。
      </Text>
    );
  }
  if (scopeOptions.length === 0) {
    return (
      <Text font="secondary-body" color="text-03">
        正在加载权限...
      </Text>
    );
  }

  // scope -> label of a selected scope that implies it (so it's auto-included).
  const lockedBy = new Map<string, string>();
  for (const scope of selectedScopes) {
    const option = scopeOptions.find((o) => o.scope === scope);
    option?.implies.forEach((implied) => lockedBy.set(implied, option.label));
  }

  return (
    <div className="grid grid-cols-2 items-start">
      {groups.map((group) => (
        <div key={group.label} className="flex flex-col items-start gap-1">
          <Text font="main-ui-action" color="text-04">
            {group.label}
          </Text>
          {group.rows.map((option) => {
            const lockReason = lockedBy.get(option.scope);
            const locked = lockReason !== undefined;
            return (
              <div key={option.scope} className="flex items-start gap-2 pl-2">
                <Checkbox
                  checked={selectedScopes.includes(option.scope) || locked}
                  disabled={disabled || locked}
                  onCheckedChange={() => toggleScope(option.scope)}
                  aria-label={`${group.label} ${option.label}`}
                />
                <div className="flex flex-col">
                  <Text font="main-ui-body" color="text-04">
                    {locked
                      ? `${option.label}（已包含在 ${lockReason} 中）`
                      : option.label}
                  </Text>
                  {/* Fixed 2-line slot so every row is the same height. */}
                  <div className="h-8 overflow-hidden">
                    <Text font="secondary-body" color="text-03" maxLines={2}>
                      {option.description}
                    </Text>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}

interface PATModalProps {
  isCreating: boolean;
  newTokenName: string;
  setNewTokenName: (name: string) => void;
  expirationDays: string;
  setExpirationDays: (days: string) => void;
  accessMode: AccessMode;
  setAccessMode: (mode: AccessMode) => void;
  scopeOptions: PatScopeOption[];
  scopesError: boolean;
  selectedScopes: string[];
  toggleScope: (scope: string) => void;
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
  accessMode,
  setAccessMode,
  scopeOptions,
  scopesError,
  selectedScopes,
  toggleScope,
  onClose,
  onCreate,
  createdToken,
}: PATModalProps) {
  if (createdToken?.token) {
    return (
      <Modal open onOpenChange={(open) => !open && onClose()}>
        <Modal.Content width="sm" height="sm">
          <Modal.Header
            title="访问令牌"
            icon={SvgKey}
            onClose={onClose}
            description="继续前请保存此令牌，之后不会再次显示。"
          />
          <Modal.Body>
            <Code showCopyButton={false}>{createdToken.token}</Code>
          </Modal.Body>
          <Modal.Footer>
            <BasicModalFooter
              submit={
                <CopyButton
                  getCopyText={() => createdToken.token}
                  prominence="primary"
                >
                  复制令牌
                </CopyButton>
              }
            />
          </Modal.Footer>
        </Modal.Content>
      </Modal>
    );
  }

  return (
    <ConfirmationModalLayout
      icon={SvgKey}
      title="创建访问令牌"
      description="使用此令牌的所有 API 请求都会继承你的访问权限，并归属到你的个人账号。"
      onClose={onClose}
      submit={
        <Button
          disabled={
            isCreating ||
            !newTokenName.trim() ||
            (accessMode === "limited" && selectedScopes.length === 0)
          }
          onClick={onCreate}
        >
          {isCreating ? "正在创建令牌..." : "创建令牌"}
        </Button>
      }
    >
      <Section gap={1}>
        <InputVertical title="令牌名称" withLabel>
          <InputTypeIn
            placeholder="为令牌命名"
            value={newTokenName}
            onChange={(e) => setNewTokenName(e.target.value)}
            variant={isCreating ? "disabled" : undefined}
            autoComplete="new-password"
          />
        </InputVertical>
        <InputVertical
          title="有效期"
          subDescription={
            expirationDays === "null"
              ? undefined
              : (() => {
                  const expiryDate = new Date();
                  expiryDate.setUTCDate(
                    expiryDate.getUTCDate() + parseInt(expirationDays)
                  );
                  expiryDate.setUTCHours(23, 59, 59, 999);
                  return `此令牌将于 ${expiryDate
                    .toISOString()
                    .replace("T", " ")
                    .replace(".999Z", " UTC")} 过期`;
                })()
          }
          withLabel
        >
          <InputSelect
            value={expirationDays}
            onValueChange={setExpirationDays}
            disabled={isCreating}
          >
            <InputSelect.Trigger placeholder="选择有效期" />
            <InputSelect.Content>
              <InputSelect.Item value="7">7 天</InputSelect.Item>
              <InputSelect.Item value="30">30 天</InputSelect.Item>
              <InputSelect.Item value="365">365 天</InputSelect.Item>
              <InputSelect.Item value="null">永不过期</InputSelect.Item>
            </InputSelect.Content>
          </InputSelect>
        </InputVertical>
        <InputVertical
          title="权限"
          subDescription={
            accessMode === "full"
              ? "继承你的全部权限。"
              : "将此令牌限制为特定能力。"
          }
          withLabel
        >
          <InputSelect
            value={accessMode}
            onValueChange={(value) => setAccessMode(value as AccessMode)}
            disabled={isCreating}
          >
            <InputSelect.Trigger placeholder="选择权限" />
            <InputSelect.Content>
              <InputSelect.Item value="full">完整访问权限</InputSelect.Item>
              <InputSelect.Item value="limited">
                受限访问权限
              </InputSelect.Item>
            </InputSelect.Content>
          </InputSelect>
        </InputVertical>
        {accessMode === "limited" && (
          <ScopeSelector
            scopeOptions={scopeOptions}
            selectedScopes={selectedScopes}
            toggleScope={toggleScope}
            scopesError={scopesError}
            disabled={isCreating}
          />
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

  const applyBackground = useCallback(
    async (bg: (typeof CHAT_BACKGROUND_OPTIONS)[number]) => {
      try {
        await updateUserChatBackground(
          bg.id === CHAT_BACKGROUND_NONE ? null : bg.id
        );
        if (bg.theme) {
          setTheme(bg.theme);
          await updateUserThemePreference(bg.theme);
        }
      } catch {
        // errors are already logged and state is rolled back via refreshUser
        // inside the update functions
      }
    },
    [updateUserChatBackground, setTheme, updateUserThemePreference]
  );
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
    onSuccess: () => toast.success("个性化设置已更新"),
    onError: () => toast.error("更新个性化设置失败"),
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
        toast.success("你的全部聊天会话已删除。");
        await refreshChatSessions();
        setShowDeleteConfirmation(false);
      } else {
        throw new Error("删除全部聊天会话失败");
      }
    } catch (error) {
      toast.error("删除全部聊天会话失败");
    } finally {
      setIsDeleting(false);
    }
  }, [pathname, router, refreshChatSessions]);

  return (
    <>
      {showDeleteConfirmation && (
        <ConfirmationModalLayout
          icon={SvgTrash}
          title="删除全部聊天"
          onClose={() => setShowDeleteConfirmation(false)}
          submit={
            <Button
              disabled={isDeleting}
              variant="danger"
              onClick={() => {
                void handleDeleteAllChats();
              }}
            >
              {isDeleting ? "正在删除..." : "删除"}
            </Button>
          }
        >
          <Section gap={0.5} alignItems="start">
            <Text color="text-05">
              你的全部聊天会话和历史记录将被永久删除，此操作无法撤销。
            </Text>
            <Text color="text-05">
              确定要删除全部聊天吗？
            </Text>
          </Section>
        </ConfirmationModalLayout>
      )}

      <Section gap={2}>
        <Section gap={0.75}>
          <Content
            title="个人资料"
            sizePreset="main-content"
            variant="section"
            width="full"
          />
          <Card>
            <InputHorizontal
              title="姓名"
              description="Glomi AI 会在应用中显示这个名称。"
              center
              withLabel
            >
              <InputTypeIn
                placeholder="你的姓名"
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
            </InputHorizontal>
            <InputHorizontal
              title="工作角色"
              description="填写你的角色，让回复更贴合你的工作场景。"
              center
              withLabel
            >
              <InputTypeIn
                placeholder="你的角色"
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
            </InputHorizontal>
          </Card>
        </Section>

        <Section gap={0.75}>
          <Content
            title="外观"
            sizePreset="main-content"
            variant="section"
            width="full"
          />
          <Card>
            <InputHorizontal
              title="颜色模式"
              description="选择你偏好的界面颜色模式。"
              center
              withLabel
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
                    自动
                  </InputSelect.Item>
                  <InputSelect.Separator />
                  <InputSelect.Item
                    value={ThemePreference.LIGHT}
                    icon={() => <ColorSwatch light />}
                  >
                    浅色
                  </InputSelect.Item>
                  <InputSelect.Item
                    value={ThemePreference.DARK}
                    icon={() => <ColorSwatch dark />}
                  >
                    深色
                  </InputSelect.Item>
                </InputSelect.Content>
              </InputSelect>
            </InputHorizontal>
            <InputVertical title="聊天背景">
              <div className="flex flex-wrap gap-2">
                {CHAT_BACKGROUND_OPTIONS.map((bg) => {
                  const currentBackgroundId =
                    user?.preferences?.chat_background ?? "none";
                  const isSelected = currentBackgroundId === bg.id;
                  const isNone = bg.src === CHAT_BACKGROUND_NONE;

                  return (
                    <button
                      key={bg.id}
                      onClick={() => applyBackground(bg)}
                      className="relative overflow-hidden rounded-lg transition-all w-[90px] h-[68px] cursor-pointer border-none p-0 bg-transparent group"
                      title={bg.label}
                      aria-label={`${bg.label}背景${
                        isSelected ? "（已选择）" : ""
                      }`}
                    >
                      {isNone ? (
                        <div className="absolute inset-0 bg-background flex items-center justify-center">
                          <span className="text-xs text-text-02">无</span>
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
            </InputVertical>
          </Card>
        </Section>

        <Divider paddingParallel="fit" paddingPerpendicular="fit" />

        <Section gap={0.75}>
          <Content
            title="危险操作"
            sizePreset="main-content"
            variant="section"
            width="full"
          />
          <Card>
            <InputHorizontal
              title="删除全部聊天"
              description="永久删除你的全部聊天会话。"
              center
            >
              <Button
                variant="danger"
                prominence="secondary"
                onClick={() => setShowDeleteConfirmation(true)}
                icon={SvgTrash}
                interaction={showDeleteConfirmation ? "hover" : "rest"}
              >
                删除全部聊天
              </Button>
            </InputHorizontal>
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
    toast.error("加载快捷方式失败");
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
          toast.success("快捷方式已删除");
          } else {
          throw new Error("删除快捷方式失败");
          }
        } catch (error) {
        toast.error("删除快捷方式失败");
      }
    },
    [shortcuts, refresh]
  );

  const handleSaveShortcut = useCallback(
    async (index: number) => {
      const shortcut = shortcuts[index];
      if (!shortcut || !shortcut.prompt.trim() || !shortcut.content.trim()) {
        toast.error("快捷指令和展开内容都必填");
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
            toast.success("快捷方式已创建");
          } else {
            throw new Error("创建快捷方式失败");
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
            toast.success("快捷方式已更新");
          } else {
            throw new Error("更新快捷方式失败");
          }
        }
      } catch (error) {
        toast.error("保存快捷方式失败");
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
                  placeholder="总结"
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
                  <Button
                    disabled={(shortcut.isNew && isEmpty) || shortcut.is_public}
                    icon={SvgMinusCircle}
                    onClick={() => void handleRemoveShortcut(index)}
                    prominence="tertiary"
                    aria-label="移除快捷方式"
                    tooltip={
                      shortcut.is_public
                        ? "无法删除公开提示词快捷方式。"
                        : undefined
                    }
                  />
                </Section>
                <InputTextArea
                  placeholder="请用 1-2 句话简洁总结以下内容："
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
    updateUserPasteAsTile,
    updateUserDefaultModel,
    updateUserDefaultAppMode,
    updateUserVoiceSettings,
  } = useUser();
  const businessTier = useTierAtLeast(Tier.BUSINESS);
  const settings = useSettingsContext();
  const { isSearchModeAvailable: searchUiEnabled } = settings;
  const llmManager = useLlmManager();
  const {
    enabled: smoothStreamingEnabled,
    setEnabled: setSmoothStreamingEnabled,
  } = useSmoothStreaming();

  const {
    personalizationValues,
    toggleUseMemories,
    toggleEnableMemoryTool,
    updateUserPreferences,
    handleSavePersonalization,
  } = useUserPersonalization(user, updateUserPersonalization, {
    onSuccess: () => toast.success("偏好设置已保存"),
    onError: () => toast.error("保存偏好设置失败"),
  });
  const [draftVoicePlaybackSpeed, setDraftVoicePlaybackSpeed] = useState(
    user?.preferences.voice_playback_speed ?? 1
  );

  useEffect(() => {
    setDraftVoicePlaybackSpeed(user?.preferences.voice_playback_speed ?? 1);
  }, [user?.preferences.voice_playback_speed]);

  const saveVoiceSettings = useCallback(
    async (settings: {
      auto_send?: boolean;
      auto_playback?: boolean;
      playback_speed?: number;
    }) => {
      try {
        await updateUserVoiceSettings(settings);
        toast.success("偏好设置已保存");
      } catch {
        toast.error("保存偏好设置失败");
      }
    },
    [updateUserVoiceSettings]
  );

  const commitVoicePlaybackSpeed = useCallback(() => {
    const currentSpeed = user?.preferences.voice_playback_speed ?? 1;
    if (Math.abs(currentSpeed - draftVoicePlaybackSpeed) < 0.001) {
      return;
    }
    void saveVoiceSettings({
      playback_speed: draftVoicePlaybackSpeed,
    });
  }, [
    draftVoicePlaybackSpeed,
    saveVoiceSettings,
    user?.preferences.voice_playback_speed,
  ]);

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
          title="聊天"
          sizePreset="main-content"
          variant="section"
          width="full"
        />
        <Card>
          <InputHorizontal
            title="默认模型"
            description="Glomi AI 会在你的对话中默认使用这个模型。"
            withLabel
          >
            <LLMPopover
              llmManager={llmManager}
              onSelect={(selected) => {
                void updateUserDefaultModel(selected);
              }}
            />
          </InputHorizontal>

          <InputHorizontal
            title="聊天自动滚动"
            description="生成回复时自动滚动到最新内容。"
            withLabel
          >
            <Switch
              checked={user?.preferences.auto_scroll}
              onCheckedChange={(checked) => {
                updateUserAutoScroll(checked);
              }}
            />
          </InputHorizontal>

          <InputHorizontal
            title="平滑流式输出"
            description="逐字显示流式回复。关闭后会按数据块即时渲染。"
            withLabel
          >
            <Switch
              checked={smoothStreamingEnabled}
              onCheckedChange={setSmoothStreamingEnabled}
            />
          </InputHorizontal>

          <InputHorizontal
            title="折叠大段粘贴内容"
            description="粘贴超过 3 行或 200 字符的内容时，折叠为紧凑卡片而不是直接插入。点击卡片可查看或编辑完整文本。"
            withLabel
          >
            <Switch
              checked={user?.preferences?.paste_as_tile ?? false}
              onCheckedChange={(checked) => {
                updateUserPasteAsTile(checked);
              }}
            />
          </InputHorizontal>

          {businessTier && (
            <Tooltip
              tooltip={
                searchUiEnabled
                  ? undefined
                  : "搜索界面已禁用，只能由管理员启用。"
              }
              side="top"
            >
              <InputHorizontal
                title="默认应用模式"
                description="选择新会话默认以搜索模式还是聊天模式开始。"
                center
                disabled={!searchUiEnabled}
                withLabel
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
                    <InputSelect.Item value="CHAT">聊天</InputSelect.Item>
                    <InputSelect.Item value="SEARCH">搜索</InputSelect.Item>
                  </InputSelect.Content>
                </InputSelect>
              </InputHorizontal>
            </Tooltip>
          )}
        </Card>
      </Section>

      <Section gap={0.75}>
        <InputVertical
          title="个人偏好"
          description="用自然语言填写你的个性化偏好。"
          withLabel
        >
          <InputTextArea
            placeholder="描述你希望系统如何回应，以及应该使用怎样的语气。"
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
        </InputVertical>
        <Content
          title="记忆"
          sizePreset="main-content"
          variant="section"
          width="full"
        />
        <Card>
          <InputHorizontal
            title="引用已保存的记忆"
            description="允许 Glomi AI 在对话中引用保存的记忆。"
            withLabel
          >
            <Switch
              checked={personalizationValues.use_memories}
              onCheckedChange={(checked) => {
                toggleUseMemories(checked);
                void handleSavePersonalization({ use_memories: checked });
              }}
            />
          </InputHorizontal>
          <InputHorizontal
            title="更新记忆"
            description="允许 Glomi AI 自动生成和更新记忆。"
            withLabel
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
          </InputHorizontal>

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
          title="提示词快捷方式"
          sizePreset="main-content"
          variant="section"
          width="full"
        />
        <Card>
          <InputHorizontal
            title="使用提示词快捷方式"
            description="启用快捷方式以快速插入常用提示词。"
            withLabel
          >
            <Switch
              checked={user?.preferences?.shortcut_enabled}
              onCheckedChange={(checked) => {
                updateUserShortcuts(checked);
              }}
            />
          </InputHorizontal>

          {user?.preferences?.shortcut_enabled && <PromptShortcuts />}
        </Card>
      </Section>

      <Section gap={0.75}>
        <Content
          title="语音"
          sizePreset="main-content"
          variant="section"
          width="full"
        />
        <Card>
          <InputHorizontal
            title="暂停时自动发送"
            description="当你停止说话时自动发送语音输入。"
            withLabel
          >
            <Switch
              checked={user?.preferences.voice_auto_send ?? false}
              onCheckedChange={(checked) => {
                void saveVoiceSettings({ auto_send: checked });
              }}
            />
          </InputHorizontal>

          <InputHorizontal
            title="自动播放"
            description="自动播放语音回复。"
            withLabel
          >
            <Switch
              checked={user?.preferences.voice_auto_playback ?? false}
              onCheckedChange={(checked) => {
                void saveVoiceSettings({ auto_playback: checked });
              }}
            />
          </InputHorizontal>

          <InputHorizontal
            title="播放速度"
            description="调整语音播放速度。"
            withLabel
          >
            <div className="flex items-center gap-3">
              <input
                type="range"
                min="0.5"
                max="2"
                step="0.1"
                value={draftVoicePlaybackSpeed}
                onChange={(e) => {
                  setDraftVoicePlaybackSpeed(parseFloat(e.target.value));
                }}
                onMouseUp={commitVoicePlaybackSpeed}
                onTouchEnd={commitVoicePlaybackSpeed}
                onKeyUp={(e) => {
                  if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
                    commitVoicePlaybackSpeed();
                  }
                }}
                className="w-24 h-2 rounded-lg appearance-none cursor-pointer bg-background-neutral-02"
              />
              <span className="text-sm text-text-02 w-10">
                {draftVoicePlaybackSpeed.toFixed(1)}x
              </span>
            </div>
          </InputHorizontal>
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
    currentPassword: Yup.string().required("请输入当前密码"),
    newPassword: Yup.string()
      .min(
        authTypeMetadata.passwordMinLength,
        `密码至少需要 ${authTypeMetadata.passwordMinLength} 个字符`
      )
      .required("New password is required"),
    confirmPassword: Yup.string()
      .oneOf([Yup.ref("newPassword")], "两次输入的密码不一致")
      .required("请确认新密码"),
  });

  // PAT state
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [newTokenName, setNewTokenName] = useState("");
  const [expirationDays, setExpirationDays] = useState<string>("30");
  const [accessMode, setAccessMode] = useState<AccessMode>("full");
  const [selectedScopes, setSelectedScopes] = useState<string[]>([]);
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
    showTokensSection ? SWR_KEYS.userPats : null,
    errorHandlingFetcher,
    {
      revalidateOnFocus: true,
      dedupingInterval: 2000,
      fallbackData: [],
    }
  );

  const { data: scopeOptions = [], error: scopeOptionsError } = useSWR<
    PatScopeOption[]
  >(
    showTokensSection && canCreateTokens ? SWR_KEYS.userPatScopes : null,
    errorHandlingFetcher,
    { fallbackData: [] }
  );

  const scopeLabels = useMemo(
    () =>
      new Map(
        scopeOptions.map((o) => [
          o.scope,
          `${o.label} ${o.group_label.toLowerCase()}`,
        ])
      ),
    [scopeOptions]
  );

  const toggleScope = useCallback((scope: string) => {
    setSelectedScopes((prev) =>
      prev.includes(scope) ? prev.filter((s) => s !== scope) : [...prev, scope]
    );
  }, []);

  // Use filter hook for searching tokens
  const {
    query,
    setQuery,
    filtered: filteredPats,
  } = useFilter(pats, (pat) => `${pat.name} ${pat.token_display}`);

  // Show error popup if SWR fetch fails
  useEffect(() => {
    if (error) {
      toast.error("加载令牌失败");
    }
  }, [error]);

  useEffect(() => {
    if (scopeOptionsError) {
      toast.error("权限选项加载失败");
    }
  }, [scopeOptionsError]);

  const createPAT = useCallback(async () => {
    if (!newTokenName.trim()) {
      toast.error("请输入令牌名称");
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
          scopes: accessMode === "limited" ? selectedScopes : null,
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
        toast.success("令牌已创建");
        // Revalidate the token list
        await mutate();
      } else {
        const errorData = await response.json();
        toast.error(errorData.detail || "令牌创建失败");
      }
    } catch (error) {
      toast.error("创建令牌时发生网络错误");
    } finally {
      setIsCreating(false);
    }
  }, [newTokenName, expirationDays, accessMode, selectedScopes, mutate]);

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
          toast.success("令牌已删除");
          setTokenToDelete(null);
        } else {
          toast.error("令牌删除失败");
        }
      } catch (error) {
        toast.error("删除令牌时发生网络错误");
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
          toast.success("密码已更新");
          setShowPasswordModal(false);
        } else {
          const errorData = await response.json();
          toast.error(errorData.detail || "密码修改失败");
        }
      } catch (error) {
        toast.error("修改密码时发生错误");
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
          accessMode={accessMode}
          setAccessMode={setAccessMode}
          scopeOptions={scopeOptions}
          scopesError={Boolean(scopeOptionsError)}
          selectedScopes={selectedScopes}
          toggleScope={toggleScope}
          onClose={() => {
            setShowCreateModal(false);
            setNewTokenName("");
            setExpirationDays("30");
            setAccessMode("full");
            setSelectedScopes([]);
            setNewlyCreatedToken(null);
          }}
          onCreate={createPAT}
          createdToken={newlyCreatedToken}
        />
      )}

      {tokenToDelete && (
        <ConfirmationModalLayout
          icon={SvgTrash}
          title="撤销访问令牌"
          onClose={() => setTokenToDelete(null)}
          submit={
            <Button
              variant="danger"
              onClick={() => deletePAT(tokenToDelete.id)}
            >
              撤销
            </Button>
          }
        >
          <Section gap={0.5} alignItems="start">
            <Text color="text-05">
              {`任何使用令牌 ${tokenToDelete.name} (${tokenToDelete.token_display}) 的应用都将失去 Glomi AI 访问权限。此操作无法撤销。`}
            </Text>
            <Text color="text-05">
              确定要撤销此令牌吗？
            </Text>
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
                title="修改密码"
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
                    {isSubmitting ? "更新中..." : "更新"}
                  </Button>
                }
                onClose={() => {
                  setShowPasswordModal(false);
                }}
              >
                <Section gap={1}>
                  <Section gap={0.25} alignItems="start">
                    <InputVertical
                      withLabel="currentPassword"
                      title="当前密码"
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
                    </InputVertical>
                  </Section>
                  <Section gap={0.25} alignItems="start">
                    <InputVertical withLabel="newPassword" title="新密码">
                      <PasswordInputTypeIn
                        name="newPassword"
                        value={values.newPassword}
                        onChange={handleChange}
                        onBlur={handleBlur}
                        error={touched.newPassword && !!errors.newPassword}
                      />
                    </InputVertical>
                  </Section>
                  <Section gap={0.25} alignItems="start">
                    <InputVertical
                      withLabel="confirmPassword"
                      title="确认新密码"
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
                    </InputVertical>
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
            title="账号"
            sizePreset="main-content"
            variant="section"
            width="full"
          />
          <Card>
            <InputHorizontal
              title="邮箱"
              description="你的账号邮箱地址。"
              center
            >
              <Text color="text-05">{user?.email ?? "anonymous"}</Text>
            </InputHorizontal>

            {showPasswordSection && (
              <InputHorizontal
                title="密码"
                description="更新你的账号密码。"
                center
              >
                <Button
                  prominence="secondary"
                  icon={SvgLock}
                  onClick={() => setShowPasswordModal(true)}
                  interaction={showPasswordModal ? "hover" : "rest"}
                >
                  修改密码
                </Button>
              </InputHorizontal>
            )}
          </Card>
        </Section>

        {showTokensSection && (
          <Section gap={0.75}>
            <Content
              title="访问令牌"
              sizePreset="main-content"
              variant="section"
              width="full"
            />
            {canCreateTokens ? (
              <Card padding={0.25}>
                <Section gap={0}>
                  <Section flexDirection="row" padding={0.25} gap={0.5}>
                    {pats.length === 0 ? (
                      <Section padding={0.5} alignItems="start">
                        <Text font="secondary-body" color="text-03">
                          {isLoading
                            ? "正在加载令牌..."
                            : "尚未创建访问令牌。"}
                        </Text>
                      </Section>
                    ) : (
                      <InputTypeIn
                        placeholder="搜索..."
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        searchIcon
                        variant="internal"
                      />
                    )}
                    <div className="shrink-0">
                      <Button
                        rightIcon={SvgPlusCircle}
                        prominence="internal"
                        interaction={showCreateModal ? "active" : "rest"}
                        onClick={() => setShowCreateModal(true)}
                      >
                        新建访问令牌
                      </Button>
                    </div>
                  </Section>

                  <Section gap={0.25}>
                    {filteredPats.map((pat) => {
                      const now = new Date();
                      const createdDate = new Date(pat.created_at);
                      const daysSinceCreation = Math.floor(
                        (now.getTime() - createdDate.getTime()) /
                          (1000 * 60 * 60 * 24)
                      );

                      let expiryText = "永不过期";
                      if (pat.expires_at) {
                        const expiresDate = new Date(pat.expires_at);
                        const daysUntilExpiry = Math.ceil(
                          (expiresDate.getTime() - now.getTime()) /
                            (1000 * 60 * 60 * 24)
                        );
                        expiryText = `${daysUntilExpiry} 天后过期`;
                      }

                      const scopeText =
                        pat.scopes === null
                          ? "完整访问权限"
                          : pat.scopes
                              .map((scope) => scopeLabels.get(scope) ?? scope)
                              .join(", ");

                      const createdText =
                        daysSinceCreation === 0
                          ? "今天创建"
                          : `${daysSinceCreation} 天前创建`;

                      const middleText = `${createdText} - ${expiryText} - ${scopeText}`;

                      return (
                        <Interactive.Container
                          key={pat.id}
                          size="fit"
                          width="full"
                        >
                          <div className="w-full bg-background-tint-01">
                            <AttachmentItemLayout
                              icon={SvgKey}
                              title={pat.name}
                              description={pat.token_display}
                              middleText={middleText}
                              rightChildren={
                                <Button
                                  icon={SvgTrash}
                                  onClick={() => setTokenToDelete(pat)}
                                  prominence="tertiary"
                                  size="sm"
                                  aria-label={`删除令牌 ${pat.name}`}
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
                  <Text font="secondary-body" color="text-03">
                    访问令牌需要有效的付费订阅。
                  </Text>
                  <Button prominence="secondary" href="/admin/billing">
                    升级套餐
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
        description={isActive ? "已连接" : "已暂停"}
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
        toast.success("已断开连接");
        setShowDisconnectConfirmation(false);
        onDisconnectSuccess();
      } else {
        throw new Error("断开连接失败");
      }
    } catch (error) {
      toast.error("断开连接失败");
    } finally {
      setIsDisconnecting(false);
    }
  }, [connector.federated_connector_id, onDisconnectSuccess]);

  return (
    <>
      {showDisconnectConfirmation && (
        <ConfirmationModalLayout
          icon={SvgUnplug}
          title={markdown(`断开 *${sourceMetadata.displayName}*`)}
          onClose={() => setShowDisconnectConfirmation(false)}
          submit={
            <Button
              disabled={isDisconnecting}
              variant="danger"
              onClick={() => void handleDisconnect()}
            >
              {isDisconnecting ? "正在断开..." : "断开连接"}
            </Button>
          }
        >
          <Section gap={0.5} alignItems="start">
            <Text color="text-05">
              {`Glomi AI 将无法再访问或搜索你的 ${sourceMetadata.displayName} 账户内容。`}
            </Text>
            <Text color="text-05">
              {`你仍可继续使用已引用 ${sourceMetadata.displayName} 内容的现有会话。`}
            </Text>
          </Section>
        </ConfirmationModalLayout>
      )}

      <Card padding={0.5}>
        <ContentAction
          icon={sourceMetadata.icon}
          title={sourceMetadata.displayName}
          description={
            connector.has_oauth_token ? "已连接" : "未连接"
          }
          sizePreset="main-content"
          variant="section"
          padding="sm"
          rightChildren={
            connector.has_oauth_token ? (
              <Button
                disabled={isDisconnecting}
                icon={SvgUnplug}
                prominence="tertiary"
                size="sm"
                onClick={() => setShowDisconnectConfirmation(true)}
              />
            ) : connector.authorize_url ? (
              <Button
                prominence="internal"
                href={connector.authorize_url}
                target="_blank"
                rightIcon={SvgArrowExchange}
              >
                连接
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
          title="连接器"
          sizePreset="main-content"
          variant="section"
          width="full"
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
          <EmptyMessageCard
            sizePreset="main-ui"
            title="你的组织尚未设置连接器。"
          />
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
