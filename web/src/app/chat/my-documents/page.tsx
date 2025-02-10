import { fetchChatData } from "@/lib/chat/fetchChatData";
import WrappedDocuments from "./WrappedDocuments";
import { redirect } from "next/navigation";
import { ChatProvider } from "@/components/context/ChatContext";
import { DocumentsProvider } from "./DocumentsContext";

export default async function GalleryPage(props: {
  searchParams: Promise<{ [key: string]: string }>;
}) {
  return (
    <DocumentsProvider>
      <WrappedDocuments />
    </DocumentsProvider>
  );
}
