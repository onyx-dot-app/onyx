import { getAdminNavId } from "@/lib/admin-sidebar-utils";
import { getTranslations } from "next-intl/server";
import { SettingsLayouts } from "@opal/layouts";
import { CUSTOM_ANALYTICS_ENABLED } from "@/lib/constants";
import { Callout } from "@/components/ui/callout";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { Text } from "@opal/components";
import { Spacer } from "@opal/components";
import CustomAnalyticsUpdateForm from "./CustomAnalyticsUpdateForm";
import { fetchAppName } from "@/lib/app/svcSS";

const route = ADMIN_ROUTES.CUSTOM_ANALYTICS;

async function Main() {
  const t = await getTranslations("admin.customAnalytics");
  const appName = await fetchAppName();

  if (!CUSTOM_ANALYTICS_ENABLED) {
    return (
      <div>
        <div className="mt-4">
          <Callout type="danger" title={t("notEnabled.title")}>
            {t.rich("notEnabled.description", {
              i: (chunks) => <i>{chunks}</i>,
              appName,
            })}
          </Callout>
        </div>
      </div>
    );
  }

  return (
    <div>
      <Text as="p">{t("intro.description", { appName })}</Text>
      <Spacer rem={2} />

      <CustomAnalyticsUpdateForm />
    </div>
  );
}

export default async function Page() {
  const tSidebar = await getTranslations("sidebar");
  const navId = getAdminNavId(route);
  const routeTitle = navId
    ? tSidebar(
        `adminNav.items.${navId}.label` as Parameters<typeof tSidebar>[0]
      )
    : route.title;
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header icon={route.icon} title={routeTitle} divider />
      <SettingsLayouts.Body>
        <Main />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
