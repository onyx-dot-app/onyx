import React, { useState, useEffect } from "react";
import { Checkbox } from "@/components/ui/checkbox";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/Modal";
import {
  Folder as FolderIcon,
  File as FileIcon,
  ChevronDown,
  ChevronRight,
} from "lucide-react";

export interface UserFolder {
  id: number;
  name: string;
  parent_id: number | null;
}

export interface UserFile {
  id: number;
  name: string;
  parent_folder_id: number | null;
}

interface FolderNode extends UserFolder {
  children: FolderNode[];
  files: UserFile[];
}

interface FilePickerProps {
  isOpen: boolean;
  onClose: () => void;
  allFolders: UserFolder[];
  setSelectedFolders: (folders: UserFolder[]) => void;
  onSave: (selectedItems: { files: number[]; folders: number[] }) => void;
}

function buildTree(folders: UserFolder[], files: UserFile[]): FolderNode[] {
  const folderMap: { [key: number]: FolderNode } = {};
  folders.forEach((folder) => {
    folderMap[folder.id] = { ...folder, children: [], files: [] };
  });

  files.forEach((file) => {
    if (file.parent_folder_id !== null && folderMap[file.parent_folder_id]) {
      folderMap[file.parent_folder_id].files.push(file);
    }
  });

  const roots: FolderNode[] = [];

  Object.values(folderMap).forEach((folder) => {
    if (folder.parent_id === null) {
      roots.push(folder);
    } else if (folderMap[folder.parent_id]) {
      folderMap[folder.parent_id].children.push(folder);
    }
  });

  return roots;
}

const FolderTreeItem: React.FC<{
  node: FolderNode;
  selectedItems: { files: number[]; folders: number[] };
  setSelectedItems: React.Dispatch<
    React.SetStateAction<{ files: number[]; folders: number[] }>
  >;
}> = ({ node, selectedItems, setSelectedItems }) => {
  const [isOpen, setIsOpen] = useState(true);

  const toggleFolder = () => {
    setIsOpen(!isOpen);
  };

  const isFolderSelected = selectedItems.folders.includes(node.id);

  const handleFolderSelect = () => {
    setSelectedItems((prev) => {
      if (isFolderSelected) {
        return {
          ...prev,
          folders: prev.folders.filter((id) => id !== node.id),
        };
      } else {
        return { ...prev, folders: [...prev.folders, node.id] };
      }
    });
  };

  return (
    <li className="my-1">
      <div className="flex items-center">
        {node.children.length > 0 || node.files.length > 0 ? (
          <button onClick={toggleFolder} className="mr-1">
            {isOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          </button>
        ) : (
          <div className="mr-4" />
        )}
        <Checkbox
          checked={isFolderSelected}
          onCheckedChange={handleFolderSelect}
        />
        <FolderIcon className="ml-2 mr-1 h-5 w-5 text-gray-600" />
        <span className="ml-1">{node.name}</span>
      </div>
      {isOpen && (
        <ul className="ml-6">
          {node.children.map((child) => (
            <FolderTreeItem
              key={child.id}
              node={child}
              selectedItems={selectedItems}
              setSelectedItems={setSelectedItems}
            />
          ))}
          {node.files.map((file) => (
            <li key={file.id} className="my-1">
              <div className="flex items-center">
                <Checkbox
                  checked={selectedItems.files.includes(file.id)}
                  onCheckedChange={() => {
                    setSelectedItems((prev) => {
                      if (prev.files.includes(file.id)) {
                        return {
                          ...prev,
                          files: prev.files.filter((id) => id !== file.id),
                        };
                      } else {
                        return { ...prev, files: [...prev.files, file.id] };
                      }
                    });
                  }}
                />
                <FileIcon className="ml-2 mr-1 h-5 w-5 text-gray-600" />
                <span className="ml-1">{file.name}</span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
};

export const FilePicker: React.FC<FilePickerProps> = ({
  isOpen,
  setSelectedFolders,
  allFolders,
  onClose,
  onSave,
}) => {
  const [fileSystem, setFileSystem] = useState<FolderNode[]>([]);
  const [selectedItems, setSelectedItems] = useState<{
    files: number[];
    folders: number[];
  }>({
    files: [],
    folders: [],
  });
  //   useEffect(() => {
  //     console.log(selectedItems.folders);
  //     console.log(allFolders);
  //     setSelectedFolders(
  //       allFolders.filter((folder) => selectedItems.folders.includes(folder.id))
  //     );
  //     console.log("SELECTED FOLDRS");
  //     console.log(
  //       allFolders.filter((folder) => selectedItems.folders.includes(folder.id))
  //     );
  //   }, [selectedItems.folders]);

  useEffect(() => {
    if (isOpen) {
      const loadFileSystem = async () => {
        const response = await fetch("/api/user/file-system");
        const data = await response.json();
        const tree = buildTree(data.folders, data.files);
        setFileSystem(tree);
      };
      loadFileSystem();
    }
  }, [isOpen]);

  const handleSave = () => {
    setSelectedFolders(
      allFolders.filter((folder) => selectedItems.folders.includes(folder.id))
    );
    onSave(selectedItems);
    onClose();
  };

  return (
    <Modal
      onOutsideClick={onClose}
      className="max-w-md"
      title="Select Files and Folders"
    >
      <div className="p-4 max-w-md mx-auto">
        <div className="max-h-96 overflow-y-auto border rounded p-2">
          <ul className="list-none">
            {fileSystem.map((node) => (
              <FolderTreeItem
                key={node.id}
                node={node}
                selectedItems={selectedItems}
                setSelectedItems={setSelectedItems}
              />
            ))}
          </ul>
        </div>
        <div className="mt-4 flex justify-end space-x-2">
          <Button onClick={onClose} variant="outline">
            Cancel
          </Button>
          <Button onClick={handleSave} variant="default">
            Select
          </Button>
        </div>
      </div>
    </Modal>
  );
};
