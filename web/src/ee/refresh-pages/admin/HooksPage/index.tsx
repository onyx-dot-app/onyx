"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useRouter } from "next/navigation";
import { SettingsLayouts } from "@opal/layouts";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { useSettings } from "@/lib/settings/hooks";
import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { Tier } from "@/lib/settings/types";
import { useHookSpecs } from "@/ee/hooks/useHookSpecs";
import { useHooks } from "@/ee/hooks/useHooks";
import useFilter from "@/hooks/useFilter";
import { toast } from "@/hooks/useToast";
import {
  useCreateModal,
  useModalClose,
} from "@/refresh-components/contexts/ModalContext";
import { Button, LinkButton, SelectCard, Text } from "@opal/components";
import { Disabled, Hoverable } from "@opal/core";
import { markdown } from "@opal/utils";
import { Content, IllustrationContent } from "@opal/layouts";
import Modal from "@/refresh-components/Modal";
import {
  SvgArrowExchange,
  SvgArrowRightDot,
  SvgBubbleText,
  SvgFileBroadcast,
  SvgShareWebhook,
  SvgPlug,
  SvgRefreshCw,
  SvgSettings,
  SvgTrash,
  SvgUnplug,
  SvgSimpleLoader,
} from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import { SvgNoResult, SvgEmpty } from "@opal/illustrations";
import { InputTypeIn } from "@opal/components";
import HookFormModal from "@/ee/refresh-pages/admin/HooksPage/HookFormModal";
import { localizeHookField } from "@/ee/refresh-pages/admin/HooksPage/hookPoints";
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
  document_push: SvgArrowRightDot,
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
  const { t } = useTranslation();

  return (
    <Modal open onOpenChange={onClose}>
      <Modal.Content width="md" height="fit">
        <Modal.Header
          // TODO(@raunakab): replace the colour of this SVG with red.
          icon={SvgUnplug}
          title={markdown(t("admin.hooks.disconnect_title", { name: hook.name }))}
          onClose={onClose}
        />
        <Modal.Body>
          <div className="flex flex-col gap-2">
            <Text font="main-ui-body" color="text-03">
              {markdown(t("admin.hooks.disconnect_body_1", { name: hook.name }))}
            </Text>
            <Text font="main-ui-body" color="text-03">
              {t("admin.hooks.disconnect_body_2")}
            </Text>
          </div>
        </Modal.Body>
        <Modal.Footer>
          <Button prominence="secondary" onClick={onClose}>
            {t("general.cancel")}
          </Button>
          <Button
            variant="danger"
            prominence="secondary"
            onClick={onDisconnectAndDelete}
          >
            {t("admin.hooks.disconnect_and_delete")}
          </Button>
          <Button variant="danger" prominence="primary" onClick={onDisconnect}>
            {t("admin.hooks.disconnect")}
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
  const { t } = useTranslation();

  return (
    <Modal open onOpenChange={onClose}>
      <Modal.Content width="md" height="fit">
        <Modal.Header
          // TODO(@raunakab): replace the colour of this SVG with red.
          icon={SvgTrash}
          title={markdown(t("admin.hooks.delete_title", { name: hook.name }))}
          onClose={onClose}
        />
        <Modal.Body>
          <div className="flex flex-col gap-2">
            <Text font="main-ui-body" color="text-03">
              {markdown(t("admin.hooks.delete_body_1", { name: hook.name }))}
            </Text>
            <Text font="main-ui-body" color="text-03">
              {t("admin.hooks.delete_body_2")}
            </Text>
          </div>
        </Modal.Body>
        <Modal.Footer>
          <Button prominence="secondary" onClick={onClose}>
            {t("general.cancel")}
          </Button>
          <Button variant="danger" prominence="primary" onClick={onDelete}>
            {t("general.delete")}
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
  const { t } = useTranslation();

  return (
    <SelectCard state="empty" padding="sm" rounding="lg" onClick={onConnect}>
      <div className="w-full flex flex-row">
        <div className="flex-1 p-2">
          <Content
            sizePreset="main-ui"
            variant="section"
            icon={Icon}
            title={localizeHookField(t, spec.hook_point, "name", spec.display_name)}
            description={localizeHookField(
              t,
              spec.hook_point,
              "desc",
              spec.description
            )}
          />

          {spec.docs_url && (
            <div className="ml-6">
              <LinkButton href={spec.docs_url} target="_blank">
                {t("admin.hooks.documentation")}
              </LinkButton>
            </div>
          )}
        </div>

        <Button
          prominence="tertiary"
          rightIcon={SvgArrowExchange}
          onClick={noProp(onConnect)}
        >
          {t("admin.hooks.connect")}
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
  const { t } = useTranslation();

  async function handleDelete() {
    deleteModal.toggle(false);
    setIsBusy(true);
    try {
      await deleteHook(hook.id);
      onDeleted();
    } catch (err) {
      console.error("Failed to delete hook:", err);
      toast.error(
        err instanceof Error ? err.message : t("admin.hooks.failed_delete")
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
        err instanceof Error ? err.message : t("admin.hooks.failed_reconnect")
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
        err instanceof Error ? err.message : t("admin.hooks.failed_deactivate")
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
        err instanceof Error ? err.message : t("admin.hooks.failed_disconnect")
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
        toast.success(t("admin.hooks.validate_success"));
      } else {
        toast.error(
          result.error_message ?? t("admin.hooks.validate_failed", { status: result.status })
        );
      }
    } catch (err) {
      console.error("Failed to validate hook:", err);
      toast.error(
        err instanceof Error ? err.message : t("admin.hooks.failed_validate")
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
                suffix={!hook.is_active ? t("admin.hooks.disconnected_suffix") : undefined}
                description={t("admin.hooks.hook_point_label", {
                  name: localizeHookField(
                    t,
                    hook.hook_point,
                    "name",
                    spec?.display_name ?? hook.hook_point
                  ),
                })}
              />

              {spec?.docs_url && (
                <div className="ml-6">
                  <LinkButton href={spec.docs_url} target="_blank">
                    {t("admin.hooks.documentation")}
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
                    {t("admin.hooks.reconnect")}
                  </Button>
                )}
              </div>

              <Disabled disabled={isBusy}>
                <div className="flex items-center justify-end pb-1 px-1 gap-1">
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
                          tooltip={t("admin.hooks.disconnect_tooltip")}
                          aria-label="Deactivate hook"
                        />
                      </Hoverable.Item>
                      <Button
                        prominence="tertiary"
                        size="md"
                        icon={SvgRefreshCw}
                        onClick={noProp(handleValidate)}
                        tooltip={t("admin.hooks.test_connection_tooltip")}
                        aria-label="Re-validate hook"
                      />
                    </>
                  ) : (
                    <Button
                      prominence="tertiary"
                      size="md"
                      icon={SvgTrash}
                      onClick={noProp(() => deleteModal.toggle(true))}
                      tooltip={t("admin.hooks.delete_tooltip")}
                      aria-label="Delete hook"
                    />
                  )}
                  <Button
                    prominence="tertiary"
                    size="md"
                    icon={SvgSettings}
                    onClick={noProp(onEdit)}
                    tooltip={t("admin.hooks.manage_tooltip")}
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
  const settings = useSettings();
  const enterpriseTier = useTierAtLeast(Tier.ENTERPRISE);
  const { t } = useTranslation();

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
    (hook: HookResponse) => {
      const spec = specs?.find(
        (s: HookPointMeta) => s.hook_point === hook.hook_point
      );
      return `${hook.name} ${localizeHookField(
        t,
        hook.hook_point,
        "name",
        spec?.display_name
      )}`;
    },
    [specs, t]
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
    const name = (spec: HookPointMeta) =>
      localizeHookField(t, spec.hook_point, "name", spec.display_name);
    const desc = (spec: HookPointMeta) =>
      localizeHookField(t, spec.hook_point, "desc", spec.description);
    return (specs ?? [])
      .filter(
        (spec: HookPointMeta) =>
          (hooksByPoint[spec.hook_point]?.length ?? 0) === 0 &&
          (!searchLower ||
            name(spec).toLowerCase().includes(searchLower) ||
            desc(spec).toLowerCase().includes(searchLower))
      )
      .sort((a: HookPointMeta, b: HookPointMeta) =>
        name(a).localeCompare(name(b))
      );
  }, [specs, hooksByPoint, search, t]);

  useEffect(() => {
    if (settings.isLoading) return;
    if (!enterpriseTier) {
      toast.info(t("admin.hooks.enterprise_required"));
      router.replace("/");
    } else if (!settings.hooks_enabled) {
      toast.info(t("admin.hooks.not_enabled"));
      router.replace("/");
    }
  }, [settings.isLoading, enterpriseTier, settings.hooks_enabled, router]);

  if (settings.isLoading || !enterpriseTier || !settings.hooks_enabled) {
    return <SvgSimpleLoader />;
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
    mutate((prev: HookResponse[] | undefined) =>
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
          description={t("admin.hooks.page_description")}
          divider
        />
        <SettingsLayouts.Body>
          {isLoading ? (
            <SvgSimpleLoader />
          ) : specsError || hooksError ? (
            <Text font="secondary-body" color="text-03">
              {specsError ? t("admin.hooks.failed_load_specs") : t("admin.hooks.failed_load_hooks")}
            </Text>
          ) : (
            <div className="flex flex-col gap-3 h-full">
              <div className="pb-3">
                <InputTypeIn
                  placeholder={t("admin.hooks.search_placeholder")}
                  value={search}
                  variant="internal"
                  searchIcon
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>

              {connectedHooks.length === 0 && unconnectedSpecs.length === 0 ? (
                <div>
                  <IllustrationContent
                    title={
                      search ? t("admin.hooks.no_results_title") : t("admin.hooks.no_hook_points_title")
                    }
                    description={
                      search ? t("admin.hooks.no_results_desc") : undefined
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
