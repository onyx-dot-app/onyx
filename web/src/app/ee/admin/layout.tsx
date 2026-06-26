import type { Metadata } from "next";
import AdminLayout from "@/layouts/admin/Layout";
import { SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED } from "@/lib/constants";
import { fetchEnterpriseSettingsSS } from "@/lib/settings/svcSS";

export async function generateMetadata(): Promise<Metadata> {
  let title = "Admin - Onyx";

  if (SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED) {
    const enterprise = await fetchEnterpriseSettingsSS();
    if (enterprise) {
      if (enterprise.application_name)
        title = `Admin - ${enterprise.application_name}`;
    }
  }

  return { title };
}

export interface LayoutProps {
  children: React.ReactNode;
}

export default async function Layout({ children }: LayoutProps) {
  return await AdminLayout({ children });
}
