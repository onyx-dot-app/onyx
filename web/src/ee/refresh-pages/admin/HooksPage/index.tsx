"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { useSettingsContext } from "@/providers/SettingsProvider";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { useHookSpecs } from "@/hooks/useHookSpecs";
import { useHooks } from "@/hooks/useHooks";
import useFilter from "@/hooks/useFilter";
import { toast } from "@/hooks/useToast";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { Button, SelectCard } from "@opal/components";
import { Disabled, Hoverable } from "@opal/core";
import { markdown } from "@opal/utils";
import { Content, IllustrationContent } from "@opal/layouts";
import Text from "@/refresh-components/texts/Text";
import Modal, { BasicModalFooter } from "@/refresh-components/Modal";
import {
  SvgArrowExchange,
  SvgBubbleText,
  SvgExternalLink,
  SvgFileBroadcast,
  SvgShareWebhook,
  SvgPlug,
  SvgRefreshCw,
  SvgSettings,
  SvgTrash,
  SvgUnplug,
} from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import SvgNoResult from "@opal/illustrations/no-result";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import HookFormModal from "@/refresh-pages/admin/HooksPage/HookFormModal";
import HookStatusPopover from "@/refresh-pages/admin/HooksPage/HookStatusPopover";
import {
  activateHook,
  deactivateHook,
  deleteHook,
  validateHook,
} from "@/refresh-pages/admin/HooksPage/svc";
import type {
  HookPointMeta,
  HookResponse,
} from "@/refresh-pages/admin/HooksPage/interfaces";

const route = ADMIN_ROUTES.HOOKS;

const HOOK_POINT_ICONS: Record<string, IconFunctionComponent> = {
  document_ingestion: SvgFileBroadcast,
  query_processing: SvgBubbleText,
};

function getHookPointIcon(hookPoint: string): IconFunctionComponent {
  return HOOK_POINT_ICONS[hookPoint] ?? SvgShareWebhook;
}

// ---------------------------------------------------------------------------
// Disconnect confirmation modal
// ---------------------------------------------------------------------------

interface DisconnectConfirmModalProps {
  hook: HookResponse;
  onClose: () => void;
  onDisconnect: () => void;
  onDisconnectAndDelete: () => void;
}

function DisconnectConfirmModal({
  hook,
  onClose,
  onDisconnect,
  onDisconnectAndDelete,
}: DisconnectConfirmModalProps) {
  return (
    <Modal open onOpenChange={(open) => !open && onClose()}>
      <Modal.Content width="md" height="fit">
        <Modal.Header
          icon={(props) => (
            <SvgUnplug {...props} className="text-action-danger-05" />
          )}
          title={`Disconnect ${hook.name}`}
          onClose={onClose}
        />
        <Modal.Body>
          <div className="flex flex-col gap-4">
            <Text mainUiBody text03>
              Onyx will stop calling this endpoint for hook{" "}
              <strong>
                <em>{hook.name}</em>
              </strong>
              . In-flight requests will continue to run. The external endpoint
              may still retain data previously sent to it. You can reconnect
              this hook later if needed.
            </Text>
            <Text mainUiBody text03>
              You can also delete this hook. Deletion cannot be undone.
            </Text>
          </div>
        </Modal.Body>
        <Modal.Footer>
          <BasicModalFooter
            cancel={
              <Button prominence="secondary" onClick={onClose}>
                Cancel
              </Button>
            }
            submit={
              <div className="flex items-center gap-2">
                <Button
                  variant="danger"
                  prominence="secondary"
                  onClick={onDisconnectAndDelete}
                >
                  Disconnect &amp; Delete
                </Button>
                <Button
                  variant="danger"
                  prominence="primary"
                  onClick={onDisconnect}
                >
                  Disconnect
                </Button>
              </div>
            }
          />
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Delete confirmation modal
// ---------------------------------------------------------------------------

interface DeleteConfirmModalProps {
  hook: HookResponse;
  onClose: () => void;
  onDelete: () => void;
}

function DeleteConfirmModal({
  hook,
  onClose,
  onDelete,
}: DeleteConfirmModalProps) {
  return (
    <Modal open onOpenChange={(open) => !open && onClose()}>
      <Modal.Content width="md" height="fit">
        <Modal.Header
          icon={(props) => (
            <SvgTrash {...props} className="text-action-danger-05" />
          )}
          title={`Delete ${hook.name}`}
          onClose={onClose}
        />
        <Modal.Body>
          <div className="flex flex-col gap-4">
            <Text mainUiBody text03>
              Hook{" "}
              <strong>
                <em>{hook.name}</em>
              </strong>{" "}
              will be permanently removed from this hook point. The external
              endpoint may still retain data previously sent to it.
            </Text>
            <Text mainUiBody text03>
              Deletion cannot be undone.
            </Text>
          </div>
        </Modal.Body>
        <Modal.Footer>
          <BasicModalFooter
            cancel={
              <Button prominence="secondary" onClick={onClose}>
                Cancel
              </Button>
            }
            submit={
              <Button variant="danger" prominence="primary" onClick={onDelete}>
                Delete
              </Button>
            }
          />
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Unconnected hook card
// ---------------------------------------------------------------------------

interface UnconnectedHookCardProps {
  spec: HookPointMeta;
  onConnect: () => void;
}

function UnconnectedHookCard({ spec, onConnect }: UnconnectedHookCardProps) {
  const Icon = getHookPointIcon(spec.hook_point);

  return (
    <SelectCard state="empty" padding="sm" onClick={onConnect}>
      <div className="w-full flex flex-row">
        <div className="flex-1 p-2">
          <Content
            sizePreset="main-ui"
            variant="section"
            icon={Icon}
            title={spec.display_name}
            description={spec.description}
          />

          {spec.docs_url && (
            <a
              href={spec.docs_url}
              target="_blank"
              rel="noopener noreferrer"
              className="ml-6 flex items-center gap-1 w-min"
            >
              <span className="underline font-secondary-body text-text-03">
                Documentation
              </span>
              <SvgExternalLink size={12} className="shrink-0" />
            </a>
          )}
        </div>

        <Button
          prominence="tertiary"
          rightIcon={SvgArrowExchange}
          onClick={onConnect}
        >
          Connect
        </Button>
      </div>
    </SelectCard>
  );
}

// ---------------------------------------------------------------------------
// Connected hook card
// ---------------------------------------------------------------------------

interface ConnectedHookCardProps {
  hook: HookResponse;
  spec: HookPointMeta | undefined;
  onEdit: () => void;
  onDeleted: () => void;
  onToggled: (updated: HookResponse) => void;
}

function ConnectedHookCard({
  hook,
  spec,
  onEdit,
  onDeleted,
  onToggled,
}: ConnectedHookCardProps) {
  const [isBusy, setIsBusy] = useState(false);
  const disconnectModal = useCreateModal();
  const deleteModal = useCreateModal();

  async function handleDelete() {
    deleteModal.toggle(false);
    setIsBusy(true);
    try {
      await deleteHook(hook.id);
      onDeleted();
    } catch (err) {
      console.error("Failed to delete hook:", err);
      toast.error(
        err instanceof Error ? err.message : "Failed to delete hook."
      );
    } finally {
      setIsBusy(false);
    }
  }

  async function handleActivate() {
    setIsBusy(true);
    try {
      const updated = await activateHook(hook.id);
      onToggled(updated);
    } catch (err) {
      console.error("Failed to reconnect hook:", err);
      toast.error(
        err instanceof Error ? err.message : "Failed to reconnect hook."
      );
    } finally {
      setIsBusy(false);
    }
  }

  async function handleDeactivate() {
    disconnectModal.toggle(false);
    setIsBusy(true);
    try {
      const updated = await deactivateHook(hook.id);
      onToggled(updated);
    } catch (err) {
      console.error("Failed to deactivate hook:", err);
      toast.error(
        err instanceof Error ? err.message : "Failed to deactivate hook."
      );
    } finally {
      setIsBusy(false);
    }
  }

  async function handleDisconnectAndDelete() {
    disconnectModal.toggle(false);
    setIsBusy(true);
    try {
      const deactivated = await deactivateHook(hook.id);
      onToggled(deactivated);
      await deleteHook(hook.id);
      onDeleted();
    } catch (err) {
      console.error("Failed to disconnect hook:", err);
      toast.error(
        err instanceof Error ? err.message : "Failed to disconnect hook."
      );
    } finally {
      setIsBusy(false);
    }
  }

  async function handleValidate() {
    setIsBusy(true);
    try {
      const result = await validateHook(hook.id);
      if (result.status === "passed") {
        toast.success("Hook validated successfully.");
      } else {
        toast.error(
          result.error_message ?? `Validation failed: ${result.status}`
        );
      }
    } catch (err) {
      console.error("Failed to validate hook:", err);
      toast.error(
        err instanceof Error ? err.message : "Failed to validate hook."
      );
    } finally {
      setIsBusy(false);
    }
  }

  const HookIcon = getHookPointIcon(hook.hook_point);

  return (
    <>
      <disconnectModal.Provider>
        <DisconnectConfirmModal
          hook={hook}
          onClose={() => disconnectModal.toggle(false)}
          onDisconnect={handleDeactivate}
          onDisconnectAndDelete={handleDisconnectAndDelete}
        />
      </disconnectModal.Provider>

      <deleteModal.Provider>
        <DeleteConfirmModal
          hook={hook}
          onClose={() => deleteModal.toggle(false)}
          onDelete={handleDelete}
        />
      </deleteModal.Provider>

      <Hoverable.Root group="connected-hook-card">
        <SelectCard state="filled" padding="sm" onClick={onEdit}>
          <div className="w-full flex flex-row">
            <div className="flex-1 p-2">
              <Content
                sizePreset="main-ui"
                variant="section"
                icon={HookIcon}
                title={
                  !hook.is_active ? markdown(`~~${hook.name}~~`) : hook.name
                }
                description={`Hook Point: ${
                  spec?.display_name ?? hook.hook_point
                }`}
              />

              {spec?.docs_url && (
                <a
                  href={spec.docs_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="ml-6 flex items-center gap-1 w-min"
                >
                  <span className="underline font-secondary-body text-text-03">
                    Documentation
                  </span>
                  <SvgExternalLink size={12} className="shrink-0" />
                </a>
              )}
            </div>

            <div className="flex flex-col items-end shrink-0">
              <div className="flex items-center gap-1">
                {hook.is_active ? (
                  <HookStatusPopover hook={hook} spec={spec} isBusy={isBusy} />
                ) : (
                  <Button
                    prominence="tertiary"
                    rightIcon={SvgPlug}
                    onClick={handleActivate}
                    disabled={isBusy}
                  >
                    Reconnect
                  </Button>
                )}
              </div>

              <Disabled disabled={isBusy}>
                <div className="flex items-center pb-1 px-1 gap-1">
                  {hook.is_active ? (
                    <>
                      <Hoverable.Item
                        group="connected-hook-card"
                        variant="opacity-on-hover"
                      >
                        <Button
                          prominence="tertiary"
                          size="md"
                          icon={SvgUnplug}
                          onClick={() => disconnectModal.toggle(true)}
                          tooltip="Disconnect Hook"
                          aria-label="Deactivate hook"
                        />
                      </Hoverable.Item>
                      <Button
                        prominence="tertiary"
                        size="md"
                        icon={SvgRefreshCw}
                        onClick={handleValidate}
                        tooltip="Test Connection"
                        aria-label="Re-validate hook"
                      />
                    </>
                  ) : (
                    <Button
                      prominence="tertiary"
                      size="md"
                      icon={SvgTrash}
                      onClick={() => deleteModal.toggle(true)}
                      tooltip="Delete"
                      aria-label="Delete hook"
                    />
                  )}
                  <Button
                    prominence="tertiary"
                    size="md"
                    icon={SvgSettings}
                    onClick={onEdit}
                    tooltip="Manage"
                    aria-label="Configure hook"
                  />
                </div>
              </Disabled>
            </div>
          </div>
        </SelectCard>
      </Hoverable.Root>
    </>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function HooksPage() {
  const router = useRouter();
  const { settings, settingsLoading } = useSettingsContext();
  const isEE = usePaidEnterpriseFeaturesEnabled();

  const [connectSpec, setConnectSpec] = useState<HookPointMeta | null>(null);
  const [editHook, setEditHook] = useState<HookResponse | null>(null);

  const { specs, isLoading: specsLoading, error: specsError } = useHookSpecs();
  const {
    hooks,
    isLoading: hooksLoading,
    error: hooksError,
    mutate,
  } = useHooks();

  const hookExtractor = useCallback(
    (hook: HookResponse) =>
      `${hook.name} ${
        specs?.find((s) => s.hook_point === hook.hook_point)?.display_name ?? ""
      }`,
    [specs]
  );

  const sortedHooks = useMemo(
    () => [...(hooks ?? [])].sort((a, b) => a.name.localeCompare(b.name)),
    [hooks]
  );

  const {
    query: search,
    setQuery: setSearch,
    filtered: connectedHooks,
  } = useFilter(sortedHooks, hookExtractor);

  const hooksByPoint = useMemo(() => {
    const map: Record<string, HookResponse[]> = {};
    for (const hook of hooks ?? []) {
      (map[hook.hook_point] ??= []).push(hook);
    }
    return map;
  }, [hooks]);

  const unconnectedSpecs = useMemo(() => {
    const searchLower = search.toLowerCase();
    return (specs ?? [])
      .filter(
        (spec) =>
          (hooksByPoint[spec.hook_point]?.length ?? 0) === 0 &&
          (!searchLower ||
            spec.display_name.toLowerCase().includes(searchLower) ||
            spec.description.toLowerCase().includes(searchLower))
      )
      .sort((a, b) => a.display_name.localeCompare(b.display_name));
  }, [specs, hooksByPoint, search]);

  useEffect(() => {
    if (settingsLoading) return;
    if (!isEE) {
      toast.info("Hook Extensions require an Enterprise license.");
      router.replace("/");
    } else if (!settings.hooks_enabled) {
      toast.info("Hook Extensions are not enabled for this deployment.");
      router.replace("/");
    }
  }, [settingsLoading, isEE, settings.hooks_enabled, router]);

  if (settingsLoading || !isEE || !settings.hooks_enabled) {
    return <SimpleLoader />;
  }

  const isLoading = specsLoading || hooksLoading;

  function handleHookSuccess(updated: HookResponse) {
    mutate((prev) => {
      if (!prev) return [updated];
      const idx = prev.findIndex((h) => h.id === updated.id);
      if (idx >= 0) {
        const next = [...prev];
        next[idx] = updated;
        return next;
      }
      return [...prev, updated];
    });
  }

  function handleHookDeleted(id: number) {
    mutate((prev) => prev?.filter((h) => h.id !== id));
  }

  const connectSpec_ =
    connectSpec ??
    (editHook
      ? specs?.find((s) => s.hook_point === editHook.hook_point)
      : undefined);

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title={route.title}
        description="Extend Onyx pipelines by registering external API endpoints as callbacks at predefined hook points."
        separator
      />
      <SettingsLayouts.Body>
        {/* Create modal */}
        {!!connectSpec && (
          <HookFormModal
            key={connectSpec?.hook_point ?? "create"}
            onOpenChange={(open) => {
              if (!open) setConnectSpec(null);
            }}
            spec={connectSpec ?? undefined}
            onSuccess={handleHookSuccess}
          />
        )}

        {/* Edit modal */}
        {!!editHook && (
          <HookFormModal
            key={editHook?.id ?? "edit"}
            onOpenChange={(open) => {
              if (!open) setEditHook(null);
            }}
            hook={editHook ?? undefined}
            spec={connectSpec_ ?? undefined}
            onSuccess={handleHookSuccess}
          />
        )}

        {isLoading ? (
          <SimpleLoader />
        ) : specsError || hooksError ? (
          <Text text03 secondaryBody>
            Failed to load
            {specsError ? " hook specifications" : " hooks"}. Please refresh the
            page.
          </Text>
        ) : (
          <div className="flex flex-col gap-3 h-full">
            <div className="pb-3">
              <InputTypeIn
                placeholder="Search hooks..."
                value={search}
                variant="internal"
                leftSearchIcon
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>

            {connectedHooks.length === 0 && unconnectedSpecs.length === 0 ? (
              <div className="h-full">
                <IllustrationContent
                  title="No results found"
                  description="Try using a different search term."
                  illustration={SvgNoResult}
                />
              </div>
            ) : (
              <div className="flex flex-col gap-2">
                {connectedHooks.map((hook) => {
                  const spec = specs?.find(
                    (s) => s.hook_point === hook.hook_point
                  );
                  return (
                    <ConnectedHookCard
                      key={hook.id}
                      hook={hook}
                      spec={spec}
                      onEdit={() => setEditHook(hook)}
                      onDeleted={() => handleHookDeleted(hook.id)}
                      onToggled={handleHookSuccess}
                    />
                  );
                })}

                {unconnectedSpecs.map((spec) => (
                  <UnconnectedHookCard
                    key={spec.hook_point}
                    spec={spec}
                    onConnect={() => setConnectSpec(spec)}
                  />
                ))}
              </div>
            )}
          </div>
        )}
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
