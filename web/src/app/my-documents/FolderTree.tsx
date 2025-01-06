import React from "react";
import { Folder as FolderIcon } from "lucide-react";

interface FolderNode {
  id: number;
  name: string;
  parent_id: number | null;
  children?: FolderNode[];
}

interface FolderTreeProps {
  treeData: FolderNode[];
  onFolderClick: (folderId: number) => void;
}

function renderTree(
  nodes: FolderNode[],
  onFolderClick: (folderId: number) => void
) {
  return (
    <ul className="ml-4 list-none">
      {nodes.map((node) => (
        <li key={node.id} className="my-1">
          <div
            className="flex items-center cursor-pointer hover:text-text-700"
            onClick={() => onFolderClick(node.id)}
          >
            <FolderIcon className="mr-1 h-4 w-4 text-text-600" />
            <span>{node.name}</span>
          </div>
          {node.children &&
            node.children.length > 0 &&
            renderTree(node.children, onFolderClick)}
        </li>
      ))}
    </ul>
  );
}

export function FolderTree({ treeData, onFolderClick }: FolderTreeProps) {
  return (
    <div className="w-64 border-r border-background-300 p-2 overflow-y-auto hidden lg:block">
      <h2 className="font-bold text-sm mb-2">Folders</h2>
      {renderTree(treeData, onFolderClick)}
    </div>
  );
}
