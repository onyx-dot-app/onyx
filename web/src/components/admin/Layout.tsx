import { redirect } from "next/navigation";
import { requireAdminAuth } from "@/lib/auth/requireAuth";
import { ClientLayout } from "./ClientLayout";
import {
  NEXT_PUBLIC_CLOUD_ENABLED,
  SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED,
} from "@/lib/constants";
import { AnnouncementBanner } from "../header/AnnouncementBanner";

export interface LayoutProps {
  children: React.ReactNode;
}

export default async function Layout({ children }: LayoutProps) {
  // Check authentication and admin role - data fetching is done client-side via SWR hooks
  const authResult = await requireAdminAuth();

  // If auth check returned a redirect, redirect immediately
  if (authResult.redirect) {
    return redirect(authResult.redirect);
  }

  return (
    <ClientLayout
      enableEnterprise={SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED}
      enableCloud={NEXT_PUBLIC_CLOUD_ENABLED}
    >
      <AnnouncementBanner />
      {children}
    </ClientLayout>
  );
}
