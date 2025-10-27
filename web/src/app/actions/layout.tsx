import {
  SidebarLayout,
  getSidebarUser,
} from "@/components/admin/SidebarLayout";
import { UserRole } from "@/lib/types";
import ChatLayout from "@/app/chat/layout";

export default async function Layout({
  children,
}: {
  children: React.ReactNode;
}) {
  const sidebarUser = await getSidebarUser();
  if (sidebarUser?.role !== UserRole.BASIC) {
    return <SidebarLayout user={sidebarUser}>{children}</SidebarLayout>;
  }
  const layout = await ChatLayout({
    children: (
      <div className="p-10 w-full h-full overflow-auto">{children}</div>
    ),
  });
  return layout;
}
