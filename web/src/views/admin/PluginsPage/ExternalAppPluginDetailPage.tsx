"use client";

import useSWR from "swr";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { Button, Modal } from "@opal/components";
import { IllustrationContent } from "@opal/layouts";
import { LineLoader } from "@opal/loaders";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import type {
  ExternalAppAdminResponse,
  BuiltInExternalAppDescriptor,
} from "@/app/craft/v1/apps/registry";
import ConfigureProviderModal from "@/app/craft/v1/apps/admin/ConfigureProviderModal";
import CreateCustomAppModal from "@/views/admin/PluginsPage/components/CreateCustomAppModal";
import PluginModalContent from "@/sections/plugins/PluginModalContent";
import { useSettings } from "@/lib/settings/hooks";
import { PLUGIN_KIND_ICONS } from "@/lib/plugins/constants";

interface ExternalAppPluginDetailPageProps {
  appId: number;
}

export default function ExternalAppPluginDetailPage({
  appId,
}: ExternalAppPluginDetailPageProps) {
  const { isGlobalHolder } = usePermissionAuthority(
    Permission.FULL_ADMIN_PANEL_ACCESS
  );
  const settings = useSettings();
  return isGlobalHolder && settings.onyx_craft_available === true ? (
    <AuthorizedExternalAppDetail appId={appId} />
  ) : null;
}

function AuthorizedExternalAppDetail({
  appId,
}: ExternalAppPluginDetailPageProps) {
  const router = useRouter();
  const t = useTranslations("actions.plugins");
  const tApps = useTranslations("admin.externalApps");
  const apps = useSWR<ExternalAppAdminResponse[], Error>(
    SWR_KEYS.buildExternalAppsAdmin,
    errorHandlingFetcher
  );
  const app = apps.data?.find((candidate) => candidate.id === appId);
  const descriptors = useSWR<BuiltInExternalAppDescriptor[], Error>(
    app && app.app_type !== "CUSTOM"
      ? SWR_KEYS.buildExternalAppsBuiltInOptions
      : null,
    errorHandlingFetcher
  );
  function close() {
    router.replace(ADMIN_ROUTES.PLUGINS.path, { scroll: false });
  }
  function saved() {
    void apps.mutate();
  }
  if (app?.app_type === "CUSTOM")
    return (
      <CreateCustomAppModal
        key={app.id}
        existingApp={app}
        onClose={close}
        onSaved={saved}
      />
    );
  const descriptor = descriptors.data?.find(
    (candidate) => candidate.app_type === app?.app_type
  );
  if (app && descriptor)
    return (
      <ConfigureProviderModal
        key={app.id}
        descriptor={descriptor}
        existingApp={app}
        onClose={close}
        onSaved={saved}
      />
    );
  const hasError = Boolean(apps.error || descriptors.error);
  return (
    <Modal open onOpenChange={(open) => !open && close()}>
      <PluginModalContent>
        <Modal.Header
          icon={PLUGIN_KIND_ICONS["external-app"]}
          title={t("kind.external-app")}
          onClose={close}
        />
        <Modal.Body alignItems="stretch">
          {hasError ? (
            <div className="flex w-full flex-col items-center gap-3">
              <IllustrationContent title={t("state.externalAppsError")} />
              <Button
                onClick={() => {
                  void apps.mutate();
                  void descriptors.mutate();
                }}
              >
                {t("state.retry.label")}
              </Button>
            </div>
          ) : !apps.data || (app && !descriptors.data) ? (
            <LineLoader lines={2} />
          ) : (
            <IllustrationContent
              title={
                app
                  ? tApps("warnings.providerUnavailable")
                  : t("state.noResults.title")
              }
            />
          )}
        </Modal.Body>
      </PluginModalContent>
    </Modal>
  );
}
