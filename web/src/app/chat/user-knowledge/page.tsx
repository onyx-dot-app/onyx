import WrappedDocuments from "./WrappedDocuments";
import { DocumentsProvider } from "./DocumentsContext";
import { UserProvider } from "@/components/user/UserProvider";

export default async function GalleryPage(props: {
  searchParams: Promise<{ [key: string]: string }>;
}) {
  return (
    <DocumentsProvider>
      <WrappedDocuments />
    </DocumentsProvider>
  );
}
