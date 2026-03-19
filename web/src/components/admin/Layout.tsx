import { redirect } from "next/navigation";
import type { Route } from "next";
import { requireAdminAuth } from "@/lib/auth/requireAuth";
import { ClientLayout } from "./ClientLayout";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { AnnouncementBanner } from "../header/AnnouncementBanner";

export interface LayoutProps {
  children: React.ReactNode;
}

export default async function Layout({ children }: LayoutProps) {
  // Check authentication and admin role - data fetching is done client-side via SWR hooks
  const authResult = await requireAdminAuth();

  // If auth check returned a redirect, redirect immediately
  if (authResult.redirect) {
    return redirect(authResult.redirect as Route);
  }

  return (
    <ClientLayout enableCloud={NEXT_PUBLIC_CLOUD_ENABLED}>
      <AnnouncementBanner />
      {children}
    </ClientLayout>
  );
}
