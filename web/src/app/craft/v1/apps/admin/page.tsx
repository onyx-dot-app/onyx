"use client";

import { useState } from "react";
import useSWR from "swr";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { Button, Divider, Text } from "@opal/components";
import Card from "@/refresh-components/cards/Card";
import { SvgPlug, SvgPlus, SvgTrash } from "@opal/icons";
import { useUser } from "@/providers/UserProvider";
import {
  BuiltInExternalAppDescriptor,
  ExternalAppAdminResponse,
  getAppTypeLogo,
} from "@/app/craft/v1/apps/registry";
import ConfigureProviderModal from "@/app/craft/v1/apps/admin/ConfigureProviderModal";
import {
  deleteExternalApp,
  setExternalAppEnabled,
} from "@/app/craft/services/externalAppsService";
import { toast } from "@/hooks/useToast";

interface ModalState {
  descriptor: BuiltInExternalAppDescriptor;
  existingApp: ExternalAppAdminResponse | null;
}

export default function ExternalAppsAdminPage() {
  const { isAdmin } = useUser();

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

  if (!isAdmin) {
    return (
      <SettingsLayouts.Root>
        <SettingsLayouts.Header
          icon={SvgPlug}
          title="External Apps"
          description="Admin access required to manage org-wide external apps."
        />
      </SettingsLayouts.Root>
    );
  }

  const isReady = descriptors !== undefined && apps !== undefined;
  const hasConfigured = isReady && apps.length > 0;

  // Edit only works for apps whose app_type still has a descriptor.
  // Apps with an orphan app_type still render but can only be
  // disabled/deleted.
  const descriptorByAppType = new Map<string, BuiltInExternalAppDescriptor>(
    (descriptors ?? []).map((d) => [d.app_type, d])
  );

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgPlug}
        title="External Apps"
        description="Connect third-party integrations so users in your org can authorize them with their personal accounts."
      />
      <SettingsLayouts.Body>
        {!isReady ? (
          <Card variant="tertiary">
            <Text font="main-content-body">Loading…</Text>
          </Card>
        ) : (
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
                        descriptor={
                          descriptorByAppType.get(app.app_type) ?? null
                        }
                        onEdit={(descriptor) =>
                          setModalState({ descriptor, existingApp: app })
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
                Add a built-in integration. You can configure multiple instances
                of the same provider (e.g. two Slack workspaces) by giving each
                a distinct name.
              </Text>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2 pt-1">
                {descriptors.map((descriptor) => (
                  <AvailableAppCard
                    key={descriptor.app_type}
                    descriptor={descriptor}
                    onClick={() =>
                      setModalState({ descriptor, existingApp: null })
                    }
                  />
                ))}
              </div>
            </section>
          </div>
        )}

        {modalState && (
          <ConfigureProviderModal
            open={modalState !== null}
            onClose={() => setModalState(null)}
            onSaved={() => mutateApps()}
            descriptor={modalState.descriptor}
            existingApp={modalState.existingApp}
          />
        )}
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}

// ── Configured app card (top section) ─────────────────────────────

interface ConfiguredAppCardProps {
  app: ExternalAppAdminResponse;
  /** Null when the app's app_type no longer has a backend descriptor. */
  descriptor: BuiltInExternalAppDescriptor | null;
  onEdit: (descriptor: BuiltInExternalAppDescriptor) => void;
  onChange: () => void;
}

function ConfiguredAppCard({
  app,
  descriptor,
  onEdit,
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
          {descriptor && (
            <Button
              prominence="secondary"
              onClick={() => onEdit(descriptor)}
              disabled={isMutating}
            >
              Edit
            </Button>
          )}
          <Button
            prominence="secondary"
            onClick={toggleEnabled}
            disabled={isMutating}
          >
            {isMutating ? "…" : app.enabled ? "Disable" : "Enable"}
          </Button>
          <Button
            prominence="tertiary"
            variant="danger"
            icon={SvgTrash}
            onClick={remove}
            disabled={isMutating}
            aria-label={`Delete ${app.name}`}
          />
        </div>
      </div>
    </Card>
  );
}

// ── Available app card (bottom section) ───────────────────────────

interface AvailableAppCardProps {
  descriptor: BuiltInExternalAppDescriptor;
  onClick: () => void;
}

function AvailableAppCard({ descriptor, onClick }: AvailableAppCardProps) {
  const Logo = getAppTypeLogo(descriptor.app_type);
  return (
    <Card>
      <div className="flex items-center gap-3 w-full">
        <Logo className="w-8 h-8" />
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
