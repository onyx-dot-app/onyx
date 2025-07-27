import { DocumentsProvider } from "@/app/chat/my-documents/DocumentsContext";
import MyDocuments from "@/app/chat/my-documents/MyDocuments";

export default async function GalleryPage(props: {
  searchParams: Promise<{ [key: string]: string }>;
}) {
  return (
    <DocumentsProvider>
      <MyDocuments />
    </DocumentsProvider>
  );
}
