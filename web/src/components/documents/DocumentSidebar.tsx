'use client';

import React, { useState } from 'react';
import { FileEntry } from '@/lib/documents/types';
import { 
  FileIcon, 
  ChevronRightIcon, 
  ChevronDownIcon
} from '@/components/icons/icons';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { FiFileText, FiGrid } from 'react-icons/fi';

interface DocumentSidebarProps {
  files: FileEntry[];
}

export function DocumentSidebar({ files }: DocumentSidebarProps) {
  const pathname = usePathname();
  
  return (
    <div className="h-full overflow-y-auto border-r border-border bg-background-sidebar dark:bg-[#000] dark:border-none">
      <div className="p-4">
        <h2 className="text-sm font-medium mb-4 text-text-500/80 dark:text-[#D4D4D4]">Files</h2>
        <div className="space-y-1">
          {files.map((file) => (
            <FileEntryItem key={file.id} file={file} level={0} />
          ))}
        </div>
      </div>
    </div>
  );
}

interface FileEntryItemProps {
  file: FileEntry;
  level: number;
}

function FileEntryItem({ file, level }: FileEntryItemProps) {
  const [expanded, setExpanded] = useState(true);
  const pathname = usePathname();
  const isActive = pathname === `/documents/${file.id}`;
  
  const toggleExpanded = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setExpanded(!expanded);
  };
  
  const handleFileClick = (e: React.MouseEvent) => {
    if (file.type === 'folder') {
      toggleExpanded(e);
    }
  };
  
  const getFileIcon = () => {
    if (file.type === 'folder') {
      return expanded ? (
        <ChevronDownIcon size={16} className="text-text-history-sidebar-button" />
      ) : (
        <ChevronRightIcon size={16} className="text-text-history-sidebar-button" />
      );
    } else if (file.fileType === 'spreadsheet') {
      return <FiGrid size={16} className="mr-1 flex-none text-green-600" />;
    } else {
      return <FiFileText size={16} className="mr-1 flex-none text-blue-600" />;
    }
  };
  
  return (
    <div>
      <div 
        className={`flex items-center py-1 px-2 rounded-md cursor-pointer ${
          isActive ? 'bg-accent-background-selected' : 'hover:bg-background-chat-hover'
        }`}
        style={{ paddingLeft: `${level * 12 + 8}px` }}
        onClick={handleFileClick}
      >
        {file.type === 'folder' ? (
          <button 
            onClick={toggleExpanded}
            className="mr-1 flex-none"
          >
            {getFileIcon()}
          </button>
        ) : (
          getFileIcon()
        )}
        
        <span className="truncate text-sm">
          {file.type === 'file' && file.url ? (
            <a 
              href={file.url} 
              target="_blank" 
              rel="noopener noreferrer"
              className="hover:underline"
              onClick={(e) => e.stopPropagation()}
            >
              {file.name}
            </a>
          ) : (
            file.name
          )}
        </span>
      </div>
      
      {file.type === 'folder' && expanded && file.children && (
        <div className="mt-1">
          {file.children.map((child) => (
            <FileEntryItem key={child.id} file={child} level={level + 1} />
          ))}
        </div>
      )}
    </div>
  );
}
