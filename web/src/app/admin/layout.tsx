import { Layout } from "@/components/admin/Layout";
import { fetchChatData } from "@/lib/chat/fetchChatData";

export default async function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return await Layout({ children });
}
