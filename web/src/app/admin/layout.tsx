import Layout from "@/layouts/admin/Layout";

export interface AdminLayoutProps {
  children: React.ReactNode;
}

export default async function AdminLayout({ children }: AdminLayoutProps) {
  return await Layout({ children });
}
