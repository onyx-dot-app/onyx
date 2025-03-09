import WrappedUserFolders from "./UserFolder";
import { DocumentsProvider, FolderResponse } from "../DocumentsContext";
import { fetchSS } from "@/lib/utilsSS";

export default async function GalleryPage(props: {
  params: Promise<{ ["id"]: string }>;
}) {
  const searchParams = await props.params;
  const response = await fetchSS(`/user/folder/${searchParams.id}`);

  // Simulate a 20-second delay
  // await new Promise((resolve) => setTimeout(resolve, 20000));
  const folderResponse: FolderResponse | undefined = response.ok
    ? await response.json()
    : null;

  return (
    <DocumentsProvider initialFolderDetails={folderResponse}>
      <WrappedUserFolders userFileId={searchParams.id} />
    </DocumentsProvider>
  );
}
