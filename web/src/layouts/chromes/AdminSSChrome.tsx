import { redirect } from "next/navigation";
import type { Route } from "next";
import { requireAdminAuth } from "@/lib/auth/requireAuth";
import AdminChrome from "@/layouts/chromes/AdminChrome";
import { AnnouncementBanner } from "@/components/header/AnnouncementBanner";

export interface AdminSSChromeProps {
  children: React.ReactNode;
}

export default async function AdminSSChrome({ children }: AdminSSChromeProps) {
  // Check authentication and admin role - data fetching is done client-side via SWR hooks
  const authResult = await requireAdminAuth();

  // If auth check returned a redirect, redirect immediately
  if (authResult.redirect) {
    return redirect(authResult.redirect as Route);
  }

  return (
    <AdminChrome>
      <AnnouncementBanner />
      {children}
    </AdminChrome>
  );
}
