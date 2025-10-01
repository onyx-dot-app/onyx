import { FileResponse } from "../DocumentsContext";

export interface UserFolder {
  id: number;
  name: string;
  parent_id: number | null;
  token_count: number | null;
}

export interface UserFile {
  id: number;
  name: string;
  parent_folder_id: number | null;
  token_count: number | null;
  link_url: string | null;
}

export interface FolderNode extends UserFolder {
  children: FolderNode[];
  files: UserFolder[];
}

export interface FilePickerModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSave: (selectedItems: { files: number[]; folders: number[] }) => void;
  title: string;
  buttonContent: string;
  selectedFiles: FileResponse[];
  addSelectedFile: (file: FileResponse) => void;
  removeSelectedFile: (file: FileResponse) => void;
}
