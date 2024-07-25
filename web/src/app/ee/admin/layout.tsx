/* Duplicate of `/app/admin/layout.tsx */

import { Layout } from "@/components/admin/Layout";

export default async function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return await Layout({ children });
}
