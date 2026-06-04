"use client";

import { useState } from "react";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { Button, Divider, Text } from "@opal/components";
import { SettingsLayouts } from "@opal/layouts";
import Card from "@/refresh-components/cards/Card";
import { SvgArrowLeft, SvgPlug, SvgPlus, SvgTrash } from "@opal/icons";
import {
  availableBuiltInDescriptors,
  BuiltInExternalAppDescriptor,
  ExternalAppAdminResponse,
  getAppTypeLogo,
} from "@/app/craft/v1/apps/registry";
import ConfigureProviderModal from "@/app/craft/v1/apps/admin/ConfigureProviderModal";
import CreateCustomAppModal from "@/app/craft/v1/apps/admin/CreateCustomAppModal";
import {
  deleteExternalApp,
  setExternalAppEnabled,
} from "@/app/craft/services/externalAppsService";
import { toast } from "@/hooks/useToast";

interface ModalState {
  descriptor: BuiltInExternalAppDescriptor;
  existingApp: ExternalAppAdminResponse | null;
}

interface ExternalAppsPageProps {
  onBack?: () => void;
}

// Admin External Apps management; members connect their own accounts on the Apps page.
export default function ExternalAppsPage({
  onBack,
}: ExternalAppsPageProps = {}) {
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgPlug}
        title="External Apps"
        description="Connect third-party integrations so users in your org can authorize them with their personal accounts in Onyx Craft."
        rightChildren={
          onBack ? (
            <div className="flex items-center gap-2">
              <Button
                prominence="secondary"
                icon={SvgArrowLeft}
                onClick={onBack}
              >
                Back
              </Button>
            </div>
          ) : undefined
        }
      />
      <SettingsLayouts.Body>
        <AppsAdminContent />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}

function AppsAdminContent() {
  const { data: descriptors } = useSWR<BuiltInExternalAppDescriptor[]>(
    SWR_KEYS.buildExternalAppsBuiltInOptions,
    errorHandlingFetcher,
    { keepPreviousData: true }
  );
  const { data: apps, mutate: mutateApps } = useSWR<ExternalAppAdminResponse[]>(
    SWR_KEYS.buildExternalAppsAdmin,
    errorHandlingFetcher,
    { keepPreviousData: true }
  );

  const [modalState, setModalState] = useState<ModalState | null>(null);
  // Custom-app create/edit modal. `existingApp: null` → create; non-null → edit.
  const [customModal, setCustomModal] = useState<{
    existingApp: ExternalAppAdminResponse | null;
  } | null>(null);

  const isReady = descriptors !== undefined && apps !== undefined;
  const hasConfigured = isReady && apps.length > 0;

  // Edit only works for apps whose app_type still has a descriptor. Apps with
  // an orphan app_type still render but can only be disabled/deleted.
  const descriptorByAppType = new Map<string, BuiltInExternalAppDescriptor>(
    (descriptors ?? []).map((d) => [d.app_type, d])
  );

  // Already-configured providers drop off the available list (one per provider).
  const availableDescriptors = availableBuiltInDescriptors(
    descriptors ?? [],
    apps ?? []
  );

  if (!isReady) {
    return (
      <Card variant="tertiary">
        <Text font="main-content-body">Loading…</Text>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {hasConfigured && (
        <>
          <section className="flex flex-col gap-2">
            <Text font="main-content-emphasis" color="text-04">
              Configured
            </Text>
            <div className="flex flex-col gap-2">
              {apps.map((app) => (
                <ConfiguredAppCard
                  key={app.id}
                  app={app}
                  descriptor={descriptorByAppType.get(app.app_type) ?? null}
                  onEdit={(descriptor) =>
                    setModalState({ descriptor, existingApp: app })
                  }
                  onEditCustom={(customApp) =>
                    setCustomModal({ existingApp: customApp })
                  }
                  onChange={() => mutateApps()}
                />
              ))}
            </div>
          </section>

          <Divider />
        </>
      )}

      <section className="flex flex-col gap-2">
        <Text font="main-content-emphasis" color="text-04">
          {hasConfigured ? "Add another" : "Available apps"}
        </Text>
        <Text font="secondary-body" color="text-03">
          Add a built-in integration. Each provider can be configured once;
          connected providers no longer appear here. Use a custom app for
          anything not listed.
        </Text>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2 pt-1">
          {availableDescriptors.map((descriptor) => (
            <AvailableAppCard
              key={descriptor.app_type}
              descriptor={descriptor}
              onClick={() => setModalState({ descriptor, existingApp: null })}
            />
          ))}
          <CreateCustomAppCard
            onClick={() => setCustomModal({ existingApp: null })}
          />
        </div>
      </section>

      {modalState && (
        <ConfigureProviderModal
          open={modalState !== null}
          onClose={() => setModalState(null)}
          onSaved={() => mutateApps()}
          descriptor={modalState.descriptor}
          existingApp={modalState.existingApp}
        />
      )}

      {customModal && (
        <CreateCustomAppModal
          open={customModal !== null}
          onClose={() => setCustomModal(null)}
          onSaved={() => mutateApps()}
          existingApp={customModal.existingApp}
        />
      )}
    </div>
  );
}

// ── Configured app card ───────────────────────────────────────────────

interface ConfiguredAppCardProps {
  app: ExternalAppAdminResponse;
  /** Null when the app's app_type no longer has a backend descriptor. */
  descriptor: BuiltInExternalAppDescriptor | null;
  /** Edit a built-in provider instance (driven by its descriptor). */
  onEdit: (descriptor: BuiltInExternalAppDescriptor) => void;
  /** Edit a custom app (no descriptor — config is on the row itself). */
  onEditCustom: (app: ExternalAppAdminResponse) => void;
  onChange: () => void;
}

function ConfiguredAppCard({
  app,
  descriptor,
  onEdit,
  onEditCustom,
  onChange,
}: ConfiguredAppCardProps) {
  const [isMutating, setIsMutating] = useState(false);
  const Logo = getAppTypeLogo(app.app_type);

  async function toggleEnabled() {
    setIsMutating(true);
    try {
      await setExternalAppEnabled(app, !app.enabled);
      onChange();
    } catch (e) {
      toast.error(
        e instanceof Error
          ? e.message
          : `Failed to ${app.enabled ? "disable" : "enable"} "${app.name}"`
      );
    } finally {
      setIsMutating(false);
    }
  }

  async function remove() {
    setIsMutating(true);
    try {
      await deleteExternalApp(app.id);
      onChange();
    } catch (e) {
      toast.error(
        e instanceof Error ? e.message : `Failed to delete "${app.name}"`
      );
    } finally {
      setIsMutating(false);
    }
  }

  return (
    <Card>
      <div className="flex items-center gap-3 w-full">
        <Logo className="w-8 h-8" />
        <div className="flex-1 flex flex-col gap-0.5">
          <Text font="main-ui-action">{app.name}</Text>
          <Text font="secondary-body" color="text-03">
            {app.enabled ? "Enabled" : "Disabled"}
          </Text>
        </div>
        <div className="flex items-center gap-2">
          {app.app_type === "CUSTOM" ? (
            <Button
              prominence="secondary"
              onClick={() => onEditCustom(app)}
              disabled={isMutating}
            >
              Edit
            </Button>
          ) : (
            descriptor && (
              <Button
                prominence="secondary"
                onClick={() => onEdit(descriptor)}
                disabled={isMutating}
              >
                Edit
              </Button>
            )
          )}
          <Button
            prominence="secondary"
            onClick={toggleEnabled}
            disabled={isMutating}
          >
            {isMutating ? "…" : app.enabled ? "Disable" : "Enable"}
          </Button>
          {/* Onyx-managed built-ins (cloud) can't be deleted — only disabled. */}
          {!app.is_onyx_managed && (
            <Button
              prominence="tertiary"
              variant="danger"
              icon={SvgTrash}
              onClick={remove}
              disabled={isMutating}
              aria-label={`Delete ${app.name}`}
            />
          )}
        </div>
      </div>
    </Card>
  );
}

// ── Available app card ────────────────────────────────────────────────

interface AvailableAppCardProps {
  descriptor: BuiltInExternalAppDescriptor;
  onClick: () => void;
}

function AvailableAppCard({ descriptor, onClick }: AvailableAppCardProps) {
  const Logo = getAppTypeLogo(descriptor.app_type);
  return (
    <Card className="h-full flex flex-col justify-center">
      <div className="flex items-center gap-3 w-full">
        <Logo className="w-8 h-8 shrink-0" />
        <div className="flex-1 flex flex-col gap-0.5">
          <Text font="main-ui-action">{descriptor.name}</Text>
          <Text font="secondary-body" color="text-03">
            {descriptor.description}
          </Text>
        </div>
        <Button icon={SvgPlus} onClick={onClick}>
          Add
        </Button>
      </div>
    </Card>
  );
}

// ── Create-custom-app card ────────────────────────────────────────────

interface CreateCustomAppCardProps {
  onClick: () => void;
}

function CreateCustomAppCard({ onClick }: CreateCustomAppCardProps) {
  return (
    <Card className="h-full flex flex-col justify-center">
      <div className="flex items-center gap-3 w-full">
        <SvgPlug className="w-8 h-8 shrink-0" />
        <div className="flex-1 flex flex-col gap-0.5">
          <Text font="main-ui-action">Custom app</Text>
          <Text font="secondary-body" color="text-03">
            Bring your own integration: upload a skill bundle and configure its
            credentials.
          </Text>
        </div>
        <Button icon={SvgPlus} onClick={onClick}>
          Create
        </Button>
      </div>
    </Card>
  );
}
