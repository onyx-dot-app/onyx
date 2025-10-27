import {
  SidebarLayout,
  getSidebarUser,
} from "@/components/admin/SidebarLayout";

export default async function Layout({
  children,
}: {
  children: React.ReactNode;
}) {
  const user = await getSidebarUser();

  return <SidebarLayout user={user}>{children}</SidebarLayout>;
}
