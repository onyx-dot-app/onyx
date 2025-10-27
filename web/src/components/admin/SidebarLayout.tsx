import { ClientLayout } from "@/components/admin/ClientLayout";
import { AnnouncementBanner } from "@/components/header/AnnouncementBanner";
import {
  SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED,
  NEXT_PUBLIC_CLOUD_ENABLED,
} from "@/lib/constants";
import { getCurrentUserSS } from "@/lib/userSS";

export async function getSidebarUser() {
  return await getCurrentUserSS();
}

export function SidebarLayout({
  user,
  children,
}: {
  user: any;
  children: React.ReactNode;
}) {
  return (
    <ClientLayout
      enableEnterprise={SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED}
      enableCloud={NEXT_PUBLIC_CLOUD_ENABLED}
      user={user}
    >
      <AnnouncementBanner />
      {children}
    </ClientLayout>
  );
}
