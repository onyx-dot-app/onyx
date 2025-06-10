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
  collapsed?: boolean;
}

export function DocumentSidebar({ files, collapsed = false }: DocumentSidebarProps) {
  const pathname = usePathname();
  
  return (
    <div className="h-full overflow-y-auto">
      <div className={`p-4 pt-0 ${collapsed ? 'px-2' : ''}`}>
        <div className="space-y-1">
          {files.map((file) => (
            <FileEntryItem 
              key={file.id} 
              file={file} 
              level={0} 
              collapsed={collapsed}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

interface FileEntryItemProps {
  file: FileEntry;
  level: number;
  collapsed?: boolean;
}

function FileEntryItem({ file, level, collapsed = false }: FileEntryItemProps) {
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
    if (collapsed) {
      return null;
    }
    
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
        className={`flex items-center py-1 rounded-md cursor-pointer transition-all duration-300 ${
          isActive 
            ? 'bg-accent-background-selected text-primary border-l-2 border-primary font-medium' 
            : 'hover:bg-background-chat-hover'
        } ${collapsed ? 'px-0 invisible' : 'px-2'}`}
        style={{ paddingLeft: collapsed ? '4px' : `${level * 12 + 8}px` }}
        onClick={handleFileClick}
        onMouseEnter={() => setShowExternalLink(true)}
        onMouseLeave={() => setShowExternalLink(false)}
        title={file.name}
      >
        {!collapsed && file.type === 'folder' ? (
          <button 
            onClick={toggleExpanded}
            className="mr-1 flex-none"
          >
            {getFileIcon()}
          </button>
        ) : (
          getFileIcon()
        )}
        
        {!collapsed ? (
          <span className="truncate text-sm flex-grow">
            {file.name}
          </span>
        ) : null}
        
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
            <FileEntryItem 
              key={child.id} 
              file={child} 
              level={level + 1} 
              collapsed={collapsed}
            />
          ))}
        </div>
      )}
    </div>
  );
}
