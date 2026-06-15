import Layout from "@/layouts/chromes/AdminChromeLayout";

export interface AdminLayoutProps {
  children: React.ReactNode;
}

export default async function AdminLayout({ children }: AdminLayoutProps) {
  return await Layout({ children });
}
