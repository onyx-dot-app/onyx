import Layout from "@/layouts/chromes/AdminSSChrome";

export interface AdminLayoutProps {
  children: React.ReactNode;
}

export default async function AdminLayout({ children }: AdminLayoutProps) {
  return await Layout({ children });
}
