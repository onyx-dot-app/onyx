'use client';

import React, { useState } from 'react';
import { FileEntry } from '@/lib/documents/types';
import { 
  FileIcon, 
  ChevronRightIcon, 
  ChevronDownIcon
} from '@/components/icons/icons';
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { FiFileText, FiGrid, FiExternalLink } from 'react-icons/fi';

interface DocumentSidebarProps {
  files: FileEntry[];
}

export function DocumentSidebar({ files }: DocumentSidebarProps) {
  const pathname = usePathname();
  
  return (
    <div className="h-full overflow-y-auto">
      <div className="p-4 pt-0">
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
  const [showExternalLink, setShowExternalLink] = useState(false);
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const currentDocId = searchParams?.get('docId');
  
  // Check if the current document is active by comparing pathname or the docId query parameter
  const isActive = pathname === `/documents/${file.id}` || file.docId === currentDocId;
  
  const toggleExpanded = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setExpanded(!expanded);
  };
  
  const handleFileClick = (e: React.MouseEvent) => {
    if (file.type === 'folder') {
      toggleExpanded(e);
    } else if (file.type === 'file' && file.docId) {
      e.preventDefault();
      e.stopPropagation();
      
      router.push(`/documents?docId=${file.docId}`);
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
          isActive 
            ? 'bg-accent-background-selected text-primary border-l-2 border-primary font-medium' 
            : 'hover:bg-background-chat-hover'
        }`}
        style={{ paddingLeft: `${level * 12 + 8}px` }}
        onClick={handleFileClick}
        onMouseEnter={() => setShowExternalLink(true)}
        onMouseLeave={() => setShowExternalLink(false)}
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
        
        <span className="truncate text-sm flex-grow">
          {file.name}
        </span>
        
        {file.type === 'file' && file.url && showExternalLink && (
          <a 
            href={file.url} 
            target="_blank" 
            rel="noopener noreferrer"
            className="ml-2 text-blue-500 hover:text-blue-700 transition-colors"
            onClick={(e) => e.stopPropagation()}
          >
            <FiExternalLink size={14} />
          </a>
        )}
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
