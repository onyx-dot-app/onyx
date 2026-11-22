"use client";

import { IconLoader, PageLoader } from "@opal/loaders";
import AdminSidebar from "@/sections/sidebar/AdminSidebar";
import type { Route } from "next";
import { useEffect, useState } from "react";
import { useSettings } from "@/lib/settings/hooks";
import { useAdminDocumentTitle } from "@/lib/app/hooks";
import {
  PendingRoute,
  useNavigation,
  usePathname,
  useRouteRendering,
} from "@opal/navigation";
import { useUser } from "@/providers/UserProvider";
import { ApplicationStatus } from "@/lib/settings/types";
import { Button, Text } from "@opal/components";
import { markdown } from "@opal/utils";
import useScreenSize from "@/hooks/useScreenSize";
import { SvgSidebar } from "@opal/icons";
import { RootLayout, useSidebarState, Section } from "@opal/layouts";
import { isVectorDbRequiredRoute, matchAdminRoute } from "@/lib/admin-routes";
import {
  getFirstPermittedAdminRoute,
  hasAnyAdminPermission,
  hasPermission,
} from "@/lib/permissions/utils";
import { OpenSearchResourceBanner } from "@/sections/banners/OpenSearchResourceWarning";
import LiteModeIndexingNotice from "@/sections/admin/LiteModeIndexingNotice";
import { useTranslations } from "next-intl";
import { AdminTopBarSlotContext } from "@/layouts/chromes/AdminTopBarSlot";

export interface AdminChromeProps {
  children: React.ReactNode;
  // Server-fetched seed (AdminSSChrome) used until /api/me loads client-side.
  initialAdminCapabilities: string[];
}

export default function AdminChrome({
  children,
  initialAdminCapabilities,
}: AdminChromeProps) {
  const t = useTranslations("common");
  const { setFolded } = useSidebarState();
  const { isMobile } = useScreenSize();
  const pathname = usePathname();
  // The proxy serves the EE pages under /admin/… URLs, but a direct visit to
  // /ee/admin/… keeps that URL.
  const base = pathname.startsWith("/ee/admin") ? "/ee/admin" : "/admin";
  const routeRendering = useRouteRendering(base);
  const { vectorDbEnabled, isLoading, application_status } = useSettings();
  useAdminDocumentTitle();
  const navigation = useNavigation();
  const { adminCapabilities: liveAdminCapabilities, isUserLoading } = useUser();
  const [topBarSlot, setTopBarSlot] = useState<HTMLElement | null>(null);

  // Seed only in flight — otherwise logout would leave the page authorized by a stale seed.
  const adminCapabilities = isUserLoading
    ? initialAdminCapabilities
    : liveAdminCapabilities;

  // Match-only per-page gate: if this page is a known admin route the user lacks the
  // permission for (a group manager landing on a full-admin page), send them to their
  // first permitted admin page. Unlisted detail sub-pages are left to the backend gate.
  const matched = matchAdminRoute(pathname);
  const denied =
    matched !== undefined &&
    !hasPermission(adminCapabilities, matched.requiredPermission);

  useEffect(() => {
    if (!denied) return;
    // Some reach left → first permitted page; fully revoked → /app (else they'd bounce to an
    // admin page they still can't open).
    navigation.go(
      (hasAnyAdminPermission(adminCapabilities)
        ? getFirstPermittedAdminRoute(adminCapabilities)
        : "/app") as Route,
      { replace: true }
    );
  }, [denied, navigation, adminCapabilities]);

  let content = children;
  // While the URL's page renders, the page being left stays as it is.
  if (!routeRendering && isVectorDbRequiredRoute(pathname)) {
    if (isLoading) {
      content = (
        <Section padding={8}>
          <IconLoader className="h-6 w-6" />
        </Section>
      );
    } else if (!vectorDbEnabled) {
      content = <LiteModeIndexingNotice />;
    }
  }

  if (denied) return null;

  return (
    <RootLayout.Root>
      {application_status === ApplicationStatus.PAYMENT_REMINDER && (
        <div className="fixed top-2 left-1/2 -translate-x-1/2 bg-status-warning-01 p-4 rounded-lg shadow-lg z-50 max-w-md text-center">
          <Text font="main-ui-body" color="text-05">
            {markdown(t("adminChrome.paymentReminder.text"))}
          </Text>
          <div className="mt-2">
            <Button width="full" {...navigation.linkTo("/admin/billing")}>
              {t("adminChrome.paymentReminder.billingButton.label")}
            </Button>
          </div>
        </div>
      )}

      <AdminSidebar />

      <RootLayout.App data-main-container>
        {/* On mobile every sidebar is an off-screen overlay, so the main
              column always needs a control to bring it back. */}
        {isMobile && (
          <RootLayout.Header>
            <Section
              flexDirection="row"
              justifyContent="start"
              gap={1}
              padding={2}
              width="auto"
              className="mx-2"
            >
              <Button
                prominence="internal"
                icon={SvgSidebar}
                aria-label={t("adminChrome.openSidebar.ariaLabel")}
                onClick={() => setFolded(false)}
              />
              <div ref={setTopBarSlot} className="contents" />
            </Section>
          </RootLayout.Header>
        )}
        <OpenSearchResourceBanner />
        <AdminTopBarSlotContext.Provider value={isMobile ? topBarSlot : null}>
          <RootLayout.MainContent>
            <PendingRoute base={base} loader={<PageLoader />}>
              {content}
            </PendingRoute>
          </RootLayout.MainContent>
        </AdminTopBarSlotContext.Provider>
      </RootLayout.App>
    </RootLayout.Root>
  );
}
