import type { Metadata } from "next";
import AdminSSChrome from "@/layouts/chromes/AdminSSChrome";
import { generateAdminTitleMetadata } from "@/lib/app/svcSS";

export async function generateMetadata(): Promise<Metadata> {
  return { title: await generateAdminTitleMetadata() };
}

export interface AdminLayoutProps {
  children: React.ReactNode;
}

export default async function AdminLayout({ children }: AdminLayoutProps) {
  return await AdminSSChrome({ children });
}
