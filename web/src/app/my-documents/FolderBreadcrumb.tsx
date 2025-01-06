import React from "react";
import { ChevronRight } from "lucide-react";

interface FolderBreadcrumbProps {
  parents: { name: string; id: number }[];
  currentFolder: { name: string; id: number };
  onBreadcrumbClick: (id: number) => void;
}

export function FolderBreadcrumb({
  parents,
  onBreadcrumbClick,
  currentFolder,
}: FolderBreadcrumbProps) {
  return (
    <div className="flex items-center space-x-2 text-sm text-text-500 mb-4">
      <span
        className="cursor-pointer hover:text-text-700"
        onClick={() => onBreadcrumbClick(-1)}
      >
        Root
      </span>
      {parents.map((parent, index) => (
        <React.Fragment key={index}>
          <ChevronRight className="h-4 w-4" />
          <span
            className="cursor-pointer hover:text-text-700"
            onClick={() => onBreadcrumbClick(parent.id)}
          >
            {parent.name}
          </span>
        </React.Fragment>
      ))}
      {currentFolder && currentFolder.id !== -1 && (
        <>
          <ChevronRight className="h-4 w-4" />
          <span className="text-text-700">{currentFolder.name}</span>
        </>
      )}
    </div>
  );
}
