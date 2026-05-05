"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { useSettingsContext } from "@/providers/SettingsProvider";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { useHookSpecs } from "@/ee/hooks/useHookSpecs";
import { useHooks } from "@/ee/hooks/useHooks";
import useFilter from "@/hooks/useFilter";
import { toast } from "@/hooks/useToast";
import {
  useCreateModal,
  useModalClose,
} from "@/refresh-components/contexts/ModalContext";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { Button, LinkButton, SelectCard, Text } from "@opal/components";
import { Disabled, Hoverable } from "@opal/core";
import { markdown } from "@opal/utils";
import { Content, IllustrationContent } from "@opal/layouts";
import Modal from "@/refresh-components/Modal";
import {
  SvgArrowExchange,
  SvgBubbleText,
  SvgFileBroadcast,
  SvgShareWebhook,
  SvgPlug,
  SvgRefreshCw,
  SvgSettings,
  SvgTrash,
  SvgUnplug,
} from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import { SvgNoResult, SvgEmpty } from "@opal/illustrations";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import HookFormModal from "@/ee/refresh-pages/admin/HooksPage/HookFormModal";
import HookStatusPopover from "@/ee/refresh-pages/admin/HooksPage/HookStatusPopover";
import {
  activateHook,
  deactivateHook,
  deleteHook,
  getHook,
  validateHook,
} from "@/ee/refresh-pages/admin/HooksPage/svc";
import type {
  HookPointMeta,
  HookResponse,
} from "@/ee/refresh-pages/admin/HooksPage/interfaces";
import { noProp } from "@/lib/utils";

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
  onDisconnect: () => void;
  onDisconnectAndDelete: () => void;
}

function DisconnectConfirmModal({
  hook,
  onDisconnect,
  onDisconnectAndDelete,
}: DisconnectConfirmModalProps) {
  const onClose = useModalClose();

  return (
    <Modal open onOpenChange={onClose}>
      <Modal.Content width="md" height="fit">
        <Modal.Header
          // TODO(@raunakab): replace the colour of this SVG with red.
          icon={SvgUnplug}
          title={markdown(`Disconnect *${hook.name}*`)}
          onClose={onClose}
        />
        <Modal.Body>
          <div className="flex flex-col gap-2">
            <Text font="main-ui-body" color="text-03">
              {markdown(
                `Onyx will stop calling this endpoint for hook ***${hook.name}***. In-flight requests will continue to run. The external endpoint may still retain data previously sent to it. You can reconnect this hook later if needed.`
              )}
            </Text>
            <Text font="main-ui-body" color="text-03">
              You can also delete this hook. Deletion cannot be undone.
            </Text>
          </div>
        </Modal.Body>
        <Modal.Footer>
          <Button prominence="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="danger"
            prominence="secondary"
            onClick={onDisconnectAndDelete}
          >
            Disconnect &amp; Delete
          </Button>
          <Button variant="danger" prominence="primary" onClick={onDisconnect}>
            Disconnect
          </Button>
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
  onDelete: () => void;
}

function DeleteConfirmModal({ hook, onDelete }: DeleteConfirmModalProps) {
  const onClose = useModalClose();

  return (
    <Modal open onOpenChange={onClose}>
      <Modal.Content width="md" height="fit">
        <Modal.Header
          // TODO(@raunakab): replace the colour of this SVG with red.
          icon={SvgTrash}
          title={markdown(`Delete *${hook.name}*`)}
          onClose={onClose}
        />
        <Modal.Body>
          <div className="flex flex-col gap-2">
            <Text font="main-ui-body" color="text-03">
              {markdown(
                `Hook ***${hook.name}*** will be permanently removed from this hook point. The external endpoint may still retain data previously sent to it.`
              )}
            </Text>
            <Text font="main-ui-body" color="text-03">
              Deletion cannot be undone.
            </Text>
          </div>
        </Modal.Body>
        <Modal.Footer>
          <Button prominence="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="danger" prominence="primary" onClick={onDelete}>
            Delete
          </Button>
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
    <SelectCard state="empty" padding="sm" rounding="lg" onClick={onConnect}>
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
            <div className="ml-6">
              <LinkButton href={spec.docs_url} target="_blank">
                Documentation
              </LinkButton>
            </div>
          )}
        </div>

        <Button
          prominence="tertiary"
          rightIcon={SvgArrowExchange}
          onClick={noProp(onConnect)}
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
      return;
    } finally {
      setIsBusy(false);
    }
    try {
      const updated = await getHook(hook.id);
      onToggled(updated);
    } catch (err) {
      console.error("Failed to refresh hook after validation:", err);
    }
  }

  const HookIcon = getHookPointIcon(hook.hook_point);

  return (
    <>
      <disconnectModal.Provider>
        <DisconnectConfirmModal
          hook={hook}
          onDisconnect={handleDeactivate}
          onDisconnectAndDelete={handleDisconnectAndDelete}
        />
      </disconnectModal.Provider>

      <deleteModal.Provider>
        <DeleteConfirmModal hook={hook} onDelete={handleDelete} />
      </deleteModal.Provider>

      <Hoverable.Root group="connected-hook-card">
        {/* TODO(@raunakab): Modify the background colour (by using `SelectCard disabled={...}` [when it lands]) to indicate when the card is "disconnected". */}
        <SelectCard state="filled" padding="sm" rounding="lg" onClick={onEdit}>
          <div className="w-full flex flex-row">
            <div className="flex-1 p-2">
              <Content
                sizePreset="main-ui"
                variant="section"
                icon={HookIcon}
                title={
                  !hook.is_active || hook.is_reachable === false
                    ? markdown(`~~${hook.name}~~`)
                    : hook.name
                }
                suffix={!hook.is_active ? "(Disconnected)" : undefined}
                description={`Hook Point: ${
                  spec?.display_name ?? hook.hook_point
                }`}
              />

              {spec?.docs_url && (
                <div className="ml-6">
                  <LinkButton href={spec.docs_url} target="_blank">
                    Documentation
                  </LinkButton>
                </div>
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
                    onClick={noProp(handleActivate)}
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
                        variant="appear-on-hover"
                      >
                        <Button
                          prominence="tertiary"
                          size="md"
                          icon={SvgUnplug}
                          onClick={noProp(() => disconnectModal.toggle(true))}
                          tooltip="Disconnect Hook"
                          aria-label="Deactivate hook"
                        />
                      </Hoverable.Item>
                      <Button
                        prominence="tertiary"
                        size="md"
                        icon={SvgRefreshCw}
                        onClick={noProp(handleValidate)}
                        tooltip="Test Connection"
                        aria-label="Re-validate hook"
                      />
                    </>
                  ) : (
                    <Button
                      prominence="tertiary"
                      size="md"
                      icon={SvgTrash}
                      onClick={noProp(() => deleteModal.toggle(true))}
                      tooltip="Delete"
                      aria-label="Delete hook"
                    />
                  )}
                  <Button
                    prominence="tertiary"
                    size="md"
                    icon={SvgSettings}
                    onClick={noProp(onEdit)}
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
        specs?.find((s: HookPointMeta) => s.hook_point === hook.hook_point)
          ?.display_name ?? ""
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
        (spec: HookPointMeta) =>
          (hooksByPoint[spec.hook_point]?.length ?? 0) === 0 &&
          (!searchLower ||
            spec.display_name.toLowerCase().includes(searchLower) ||
            spec.description.toLowerCase().includes(searchLower))
      )
      .sort((a: HookPointMeta, b: HookPointMeta) =>
        a.display_name.localeCompare(b.display_name)
      );
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
    mutate((prev: HookResponse[] | undefined) => {
      if (!prev) return [updated];
      const idx = prev.findIndex((h: HookResponse) => h.id === updated.id);
      if (idx >= 0) {
        const next = [...prev];
        next[idx] = updated;
        return next;
      }
      return [...prev, updated];
    });
  }

  function handleHookDeleted(id: number) {
    mutate(
      (prev: HookResponse[] | undefined) =>
        prev?.filter((h: HookResponse) => h.id !== id)
    );
  }

  const connectSpec_ =
    connectSpec ??
    (editHook
      ? specs?.find((s: HookPointMeta) => s.hook_point === editHook.hook_point)
      : undefined);

  return (
    <>
      {/* Create modal */}
      {!!connectSpec && (
        <HookFormModal
          key={connectSpec?.hook_point ?? "create"}
          onOpenChange={(open: boolean) => {
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
          onOpenChange={(open: boolean) => {
            if (!open) setEditHook(null);
          }}
          hook={editHook ?? undefined}
          spec={connectSpec_ ?? undefined}
          onSuccess={handleHookSuccess}
        />
      )}

      <SettingsLayouts.Root>
        <SettingsLayouts.Header
          icon={route.icon}
          title={route.title}
          description="Extend Onyx pipelines by registering external API endpoints as callbacks at predefined hook points."
          divider
        />
        <SettingsLayouts.Body>
          {isLoading ? (
            <SimpleLoader />
          ) : specsError || hooksError ? (
            <Text font="secondary-body" color="text-03">
              {`Failed to load${
                specsError ? " hook specifications" : " hooks"
              }. Please refresh the page.`}
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
                <div>
                  <IllustrationContent
                    title={
                      search ? "No results found" : "No hook points available"
                    }
                    description={
                      search ? "Try using a different search term." : undefined
                    }
                    illustration={search ? SvgNoResult : SvgEmpty}
                  />
                </div>
              ) : (
                <div className="flex flex-col gap-2">
                  {connectedHooks.map((hook) => {
                    const spec = specs?.find(
                      (s: HookPointMeta) => s.hook_point === hook.hook_point
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

                  {unconnectedSpecs.map((spec: HookPointMeta) => (
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
    </>
  );
}
