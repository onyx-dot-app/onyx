import WrappedDocuments from "./WrappedDocuments";
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
