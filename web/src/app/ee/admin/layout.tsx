import Layout from "@/components/admin/Layout";

export interface AdminLayoutProps {
  children: React.ReactNode;
}

export default async function AdminLayout({ children }: AdminLayoutProps) {
  return await Layout({ children });
}
