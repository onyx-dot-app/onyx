import AdminSSChrome from "@/layouts/chromes/AdminSSChrome";

export interface AdminLayoutProps {
  children: React.ReactNode;
}

export default async function AdminLayout({ children }: AdminLayoutProps) {
  return await AdminSSChrome({ children });
}
