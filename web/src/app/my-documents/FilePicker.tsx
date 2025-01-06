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
  allFiles: UserFile[];
  setUserFiles: (files: UserFile[]) => void;
  selectedFolders: UserFolder[];
  userFiles: UserFile[];
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
  parentNode?: FolderNode;
}> = ({ node, selectedItems, setSelectedItems, parentNode }) => {
  const [isOpen, setIsOpen] = useState(true);

  const toggleFolder = () => {
    setIsOpen(!isOpen);
  };

  const isFolderSelected = selectedItems.folders.includes(node.id);

  const getAllDescendantIds = (
    folder: FolderNode
  ): { folderIds: number[]; fileIds: number[] } => {
    let folderIds: number[] = [];
    let fileIds: number[] = [];

    const traverse = (node: FolderNode) => {
      folderIds.push(node.id);
      fileIds.push(...node.files.map((file) => file.id));
      node.children.forEach(traverse);
    };

    traverse(folder);
    return { folderIds, fileIds };
  };

  const shouldFolderBeSelected = (
    folder: FolderNode,
    newlySelectedItem: number,
    newlySelectedItemType: "file" | "folder"
  ): boolean => {
    const allFilesSelected = folder.files.every((file) => {
      const isSelected =
        selectedItems.files.includes(file.id) ||
        (newlySelectedItemType === "file" && newlySelectedItem === file.id);
      return isSelected;
    });

    const allChildrenSelected = folder.children.every((child) => {
      const isSelected =
        selectedItems.folders.includes(child.id) ||
        (newlySelectedItemType === "folder" && newlySelectedItem === child.id);
      return isSelected;
    });

    const shouldBeSelected = allFilesSelected && allChildrenSelected;
    return shouldBeSelected;
  };

  const updateParentFolderSelection = (currentNode: FolderNode) => {
    if (parentNode) {
      // const shouldSelect = shouldFolderBeSelected(currentNode);
      // setSelectedItems((prev) => {
      //   const newFolders = shouldSelect
      //     ? Array.from(new Set([...prev.folders, currentNode.id]))
      //     : prev.folders.filter((id) => id !== currentNode.id);
      //   return { ...prev, folders: newFolders };
      // });
    }
  };

  const handleFolderSelect = () => {
    setSelectedItems((prev) => {
      const { folderIds, fileIds } = getAllDescendantIds(node);

      if (isFolderSelected) {
        const newState = {
          folders: prev.folders.filter((id) => !folderIds.includes(id)),
          files: prev.files.filter((id) => !fileIds.includes(id)),
        };
        setTimeout(() => updateParentFolderSelection(node), 0);
        return newState;
      } else {
        const newState = {
          folders: Array.from(new Set([...prev.folders, ...folderIds])),
          files: Array.from(new Set([...prev.files, ...fileIds])),
        };
        setTimeout(() => updateParentFolderSelection(node), 0);
        return newState;
      }
    });
  };

  const handleFileSelect = (fileId: number) => {
    setSelectedItems((prev) => {
      const newFiles = prev.files.includes(fileId)
        ? prev.files.filter((id) => id !== fileId)
        : [...prev.files, fileId];

      const newState = { ...prev, files: newFiles };
      setTimeout(() => {
        const shouldSelect = shouldFolderBeSelected(node, fileId, "file");

        setSelectedItems((prevState) => {
          const newFolders = shouldSelect
            ? Array.from(new Set([...prevState.folders, node.id]))
            : prevState.folders.filter((id) => id !== node.id);
          updateParentFolderSelection(node);
          return { ...prevState, folders: newFolders };
        });
      }, 100);
      return newState;
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
        <FolderIcon className="ml-2 mr-1 h-5 w-5 text-text-600" />
        <span className="ml-1">
          {node.name}
          {node.id}
        </span>
      </div>
      {isOpen && (
        <ul className="ml-6">
          {node.children.map((child) => (
            <FolderTreeItem
              key={child.id}
              node={child}
              selectedItems={selectedItems}
              setSelectedItems={setSelectedItems}
              parentNode={node}
            />
          ))}
          {node.files.map((file) => (
            <li key={file.id} className="my-1">
              <div className="flex items-center">
                <Checkbox
                  checked={selectedItems.files.includes(file.id)}
                  onCheckedChange={() => {
                    handleFileSelect(file.id);
                  }}
                />
                <FileIcon className="ml-2 mr-1 h-5 w-5 text-text-600" />
                <span className="ml-1">
                  {file.name}
                  {file.id}
                </span>
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
  setUserFiles,
  allFolders,
  allFiles,
  selectedFolders,
  userFiles,
  onClose,
  onSave,
}) => {
  const [fileSystem, setFileSystem] = useState<FolderNode[]>([]);
  const [selectedItems, setSelectedItems] = useState<{
    files: number[];
    folders: number[];
  }>({
    files: userFiles.map((file) => file.id),
    folders: selectedFolders.map((folder) => folder.id),
  });

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

  const getAllDescendantIds = (
    folder: FolderNode
  ): { folderIds: number[]; fileIds: number[] } => {
    let folderIds: number[] = [];
    let fileIds: number[] = [];

    const traverse = (node: FolderNode) => {
      folderIds.push(node.id);
      fileIds.push(...node.files.map((file) => file.id));
      node.children.forEach(traverse);
    };

    traverse(folder);
    return { folderIds, fileIds };
  };

  const isFullySelected = (node: FolderNode): boolean => {
    const allDescendants = getAllDescendantIds(node);
    return (
      allDescendants.folderIds.every((id: number) =>
        selectedItems.folders.includes(id)
      ) &&
      allDescendants.fileIds.every((id: number) =>
        selectedItems.files.includes(id)
      )
    );
  };

  const getOptimizedSelection = (
    nodes: FolderNode[]
  ): { folders: number[]; files: number[] } => {
    let optimizedFolders: number[] = [];
    let optimizedFiles: number[] = [];

    const processNode = (node: FolderNode) => {
      if (isFullySelected(node)) {
        optimizedFolders.push(node.id);
      } else {
        node.children.forEach(processNode);
        node.files.forEach((file) => {
          if (selectedItems.files.includes(file.id)) {
            optimizedFiles.push(file.id);
          }
        });
      }
    };

    nodes.forEach(processNode);
    return { folders: optimizedFolders, files: optimizedFiles };
  };

  const handleSave = () => {
    const optimizedSelection = getOptimizedSelection(fileSystem);

    setSelectedFolders(
      allFolders.filter((folder) =>
        optimizedSelection.folders.includes(folder.id)
      )
    );

    const selectedFiles = optimizedSelection.files
      .map((fileId) => allFiles.find((file) => file.id === fileId))
      .filter((file): file is UserFile => file !== undefined);
    setUserFiles(selectedFiles);
    onSave(optimizedSelection);
    onClose();
  };

  return (
    <Modal
      onOutsideClick={onClose}
      className="max-w-xl"
      title="Select Files and Folders"
    >
      <div className="p-4  w-full  mx-auto">
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
