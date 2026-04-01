"use client";

import { useState } from "react";
import { toast } from "@/hooks/useToast";
import { Button } from "@opal/components";
import { Disabled } from "@opal/core";
import { cn } from "@/lib/utils";
import { markdown } from "@opal/utils";
import { Content } from "@opal/layouts";
import Card from "@/refresh-components/cards/Card";
import Text from "@/refresh-components/texts/Text";
import { Section } from "@/layouts/general-layouts";
import {
  SvgExternalLink,
  SvgPlug,
  SvgRefreshCw,
  SvgSettings,
  SvgTrash,
  SvgUnplug,
} from "@opal/icons";
import Modal, { BasicModalFooter } from "@/refresh-components/Modal";
import type {
  HookPointMeta,
  HookResponse,
} from "@/refresh-pages/admin/HooksPage/interfaces";
import {
  activateHook,
  deactivateHook,
  deleteHook,
  validateHook,
} from "@/refresh-pages/admin/HooksPage/svc";
import { getHookPointIcon } from "@/refresh-pages/admin/HooksPage/hookPointIcons";
import HookStatusPopover from "@/refresh-pages/admin/HooksPage/HookStatusPopover";

// ---------------------------------------------------------------------------
// Sub-component: disconnect confirmation modal
// ---------------------------------------------------------------------------

interface DisconnectConfirmModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  hook: HookResponse;
  onDisconnect: () => void;
  onDisconnectAndDelete: () => void;
}

function DisconnectConfirmModal({
  open,
  onOpenChange,
  hook,
  onDisconnect,
  onDisconnectAndDelete,
}: DisconnectConfirmModalProps) {
  return (
    <Modal open={open} onOpenChange={onOpenChange}>
      <Modal.Content width="md" height="fit">
        <Modal.Header
          icon={(props) => (
            <SvgUnplug {...props} className="text-action-danger-05" />
          )}
          title={`Disconnect ${hook.name}`}
          onClose={() => onOpenChange(false)}
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
              <Button
                prominence="secondary"
                onClick={() => onOpenChange(false)}
              >
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
// Sub-component: delete confirmation modal
// ---------------------------------------------------------------------------

interface DeleteConfirmModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  hook: HookResponse;
  onDelete: () => void;
}

function DeleteConfirmModal({
  open,
  onOpenChange,
  hook,
  onDelete,
}: DeleteConfirmModalProps) {
  return (
    <Modal open={open} onOpenChange={onOpenChange}>
      <Modal.Content width="md" height="fit">
        <Modal.Header
          icon={(props) => (
            <SvgTrash {...props} className="text-action-danger-05" />
          )}
          title={`Delete ${hook.name}`}
          onClose={() => onOpenChange(false)}
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
              <Button
                prominence="secondary"
                onClick={() => onOpenChange(false)}
              >
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
// ConnectedHookCard
// ---------------------------------------------------------------------------

export interface ConnectedHookCardProps {
  hook: HookResponse;
  spec: HookPointMeta | undefined;
  onEdit: () => void;
  onDeleted: () => void;
  onToggled: (updated: HookResponse) => void;
}

export default function ConnectedHookCard({
  hook,
  spec,
  onEdit,
  onDeleted,
  onToggled,
}: ConnectedHookCardProps) {
  const [isBusy, setIsBusy] = useState(false);
  const [disconnectConfirmOpen, setDisconnectConfirmOpen] = useState(false);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);

  async function handleDelete() {
    setDeleteConfirmOpen(false);
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
    setDisconnectConfirmOpen(false);
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
    setDisconnectConfirmOpen(false);
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
      <DisconnectConfirmModal
        open={disconnectConfirmOpen}
        onOpenChange={setDisconnectConfirmOpen}
        hook={hook}
        onDisconnect={handleDeactivate}
        onDisconnectAndDelete={handleDisconnectAndDelete}
      />
      <DeleteConfirmModal
        open={deleteConfirmOpen}
        onOpenChange={setDeleteConfirmOpen}
        hook={hook}
        onDelete={handleDelete}
      />
      <Card
        variant="primary"
        padding={0.5}
        gap={0}
        className={cn(
          "hover:border-border-02",
          !hook.is_active && "!bg-background-neutral-02"
        )}
      >
        <div className="w-full flex flex-row">
          <div className="flex-1 p-2">
            <Content
              sizePreset="main-ui"
              variant="section"
              icon={HookIcon}
              title={!hook.is_active ? markdown(`~~${hook.name}~~`) : hook.name}
              description={`Hook Point: ${
                spec?.display_name ?? hook.hook_point
              }`}
            />

            {spec?.docs_url && (
              <a
                href={spec.docs_url}
                target="_blank"
                rel="noopener noreferrer"
                className="pl-6 flex items-center gap-1 w-fit"
              >
                <span className="underline font-secondary-body text-text-03">
                  Documentation
                </span>
                <SvgExternalLink size={12} className="shrink-0" />
              </a>
            )}
          </div>

          <Section
            flexDirection="column"
            alignItems="end"
            width="fit"
            height="fit"
            gap={0}
          >
            <div className="flex items-center gap-1">
              {hook.is_active ? (
                <HookStatusPopover hook={hook} spec={spec} isBusy={isBusy} />
              ) : (
                <div
                  className={cn(
                    "flex items-center gap-1 p-2",
                    isBusy ? "opacity-50 pointer-events-none" : "cursor-pointer"
                  )}
                  onClick={handleActivate}
                >
                  <Text mainUiAction text03>
                    Reconnect
                  </Text>
                  <SvgPlug size={16} className="text-text-03 shrink-0" />
                </div>
              )}
            </div>
            <Disabled disabled={isBusy}>
              <div className="flex items-center gap-0.5 pl-1 pr-1 pb-1">
                {hook.is_active ? (
                  <>
                    <Button
                      prominence="tertiary"
                      size="sm"
                      icon={SvgUnplug}
                      onClick={() => setDisconnectConfirmOpen(true)}
                      tooltip="Disconnect Hook"
                      aria-label="Deactivate hook"
                    />
                    <Button
                      prominence="tertiary"
                      size="sm"
                      icon={SvgRefreshCw}
                      onClick={handleValidate}
                      tooltip="Test Connection"
                      aria-label="Re-validate hook"
                    />
                  </>
                ) : (
                  <Button
                    prominence="tertiary"
                    size="sm"
                    icon={SvgTrash}
                    onClick={() => setDeleteConfirmOpen(true)}
                    tooltip="Delete"
                    aria-label="Delete hook"
                  />
                )}
                <Button
                  prominence="tertiary"
                  size="sm"
                  icon={SvgSettings}
                  onClick={onEdit}
                  tooltip="Manage"
                  aria-label="Configure hook"
                />
              </div>
            </Disabled>
          </Section>
        </div>
      </Card>
    </>
  );
}
