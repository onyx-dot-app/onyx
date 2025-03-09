import { useDocumentsContext } from "../DocumentsContext";

export default function UserFolder({ userFileId }: { userFileId: string }) {
  const { folders } = useDocumentsContext();

  return <div>{folders.length}</div>;
}
