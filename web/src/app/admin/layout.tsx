import { Layout as GenericLayout } from "@/components/admin/Layout";

interface LayoutProps {
  children: React.ReactNode;
}

export default async function Layout({ children }: LayoutProps) {
  return await GenericLayout({ children });
}
