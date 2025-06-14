'use client';

import { Button } from '@/components/ui/button';
import { FiPlus, FiX, FiFolder, FiChevronDown, FiFileText, FiGrid } from 'react-icons/fi';
import { useState, useRef, useEffect } from 'react';
import { FileEntry } from '@/lib/documents/types';

export interface DocumentContent {
  id: string;
  title: string;
  content: string;
  type: string;
}

interface DocumentSelectorProps {
  documentsInContext: DocumentContent[];
  onAddDocument?: (document: DocumentContent) => void;
  onRemoveDocument?: (documentId: string) => void;
  availableFiles?: FileEntry[]; // Files from the left sidebar (precision files)
  className?: string;
}

export function DocumentSelector({
  documentsInContext,
  onAddDocument,
  onRemoveDocument,
  availableFiles = [],
  className = ''
}: DocumentSelectorProps) {
  const [isFilesDropdownOpen, setIsFilesDropdownOpen] = useState(false);
  const [loadingFileId, setLoadingFileId] = useState<string | null>(null);
  const filesDropdownRef = useRef<HTMLDivElement>(null);


  const handleRemoveDocument = (documentId: string) => {
    if (onRemoveDocument) {
      onRemoveDocument(documentId);
    }
  };


  const handleFileAdd = async (file: FileEntry) => {
    if (!onAddDocument || !file.docId) return;
    
    // Check if already in context
    const isAlreadyAdded = documentsInContext.some(existingDoc => existingDoc.id === file.docId);
    if (isAlreadyAdded) {
      setIsFilesDropdownOpen(false);
      return;
    }

    setLoadingFileId(file.docId);
    
    try {
      // Fetch the document content based on file type
      let content = '';
      
      if (file.fileType === 'spreadsheet') {
        // For spreadsheets, we'd need to implement a way to fetch sheet content
        // For now, we'll use a placeholder
        content = `Spreadsheet: ${file.name}`;
      } else {
        // For documents, we can try to fetch from Google Docs API
        // This would require implementing a proper API call
        // For now, we'll use a placeholder  
        content = `Document: ${file.name}`;
      }
      
      const doc: DocumentContent = {
        id: file.docId,
        title: file.name,
        content: content,
        type: file.fileType || 'document'
      };
      
      onAddDocument(doc);
    } catch (error) {
      console.error('Error fetching document content:', error);
      // Still add the document with basic info even if content fetch fails
      const doc: DocumentContent = {
        id: file.docId,
        title: file.name,
        content: `Unable to load content for: ${file.name}`,
        type: file.fileType || 'document'
      };
      onAddDocument(doc);
    } finally {
      setLoadingFileId(null);
      setIsFilesDropdownOpen(false);
    }
  };

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (filesDropdownRef.current && !filesDropdownRef.current.contains(event.target as Node)) {
        setIsFilesDropdownOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, []);

  // Helper function to truncate long titles intelligently
  const getTruncatedTitle = (title: string, maxLength: number = 25) => {
    if (!title) return 'Untitled Document';
    if (title.length <= maxLength) return title;
    
    // Try to truncate at word boundaries
    const truncated = title.substring(0, maxLength);
    const lastSpace = truncated.lastIndexOf(' ');
    
    // If we can find a reasonable word boundary, use it
    if (lastSpace > maxLength * 0.6) {
      return truncated.substring(0, lastSpace) + '...';
    }
    
    return truncated + '...';
  };

  return (
    <div className={`flex flex-col gap-2 p-3 border-b border-border relative overflow-visible ${className}`}>
      <div className="flex items-center gap-2 min-w-0 overflow-visible">
        <span className="text-sm text-muted-foreground font-medium flex-shrink-0">Documents:</span>
        
        
        {/* Browse available documents button */}
        <div className="relative overflow-visible" ref={filesDropdownRef}>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setIsFilesDropdownOpen(!isFilesDropdownOpen)}
              className="flex items-center gap-1 px-3 py-1 h-auto text-xs flex-shrink-0"
              title="Add documents from available files"
              disabled={availableFiles.length === 0}
            >
              <FiFolder size={12} />
              Add Documents ({availableFiles.filter(f => f.type === 'file' && f.docId && !documentsInContext.some(existing => existing.id === f.docId)).length})
              <FiChevronDown size={10} className={`transition-transform ${isFilesDropdownOpen ? 'rotate-180' : ''}`} />
            </Button>
            
            {/* Documents Dropdown menu */}
            {isFilesDropdownOpen && (
              <div className="absolute top-full left-0 mt-1 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-md shadow-lg z-[9999] min-w-64 max-w-80">
                <div className="py-1 max-h-60 overflow-y-auto">
                  {availableFiles.filter(f => f.type === 'file' && f.docId).length === 0 ? (
                    <div className="px-3 py-2 text-xs text-gray-500 dark:text-gray-400">
                      No documents available to add
                    </div>
                  ) : (
                    <>
                      {availableFiles
                        .filter(file => file.type === 'file' && file.docId && !documentsInContext.some(existing => existing.id === file.docId))
                        .map((file) => (
                          <button
                            key={file.docId}
                            onClick={() => handleFileAdd(file)}
                            disabled={loadingFileId === file.docId}
                            className="w-full px-3 py-2 text-left text-xs hover:bg-gray-100 dark:hover:bg-gray-700 flex items-start gap-2 disabled:opacity-50"
                          >
                            <div className="flex items-center gap-1 flex-shrink-0 mt-0.5">
                              {file.fileType === 'spreadsheet' ? (
                                <FiGrid size={12} className="text-green-600" />
                              ) : (
                                <FiFileText size={12} className="text-blue-600" />
                              )}
                            </div>
                            <div className="flex-1 min-w-0">
                              <div className="font-medium truncate" title={file.name}>
                                {getTruncatedTitle(file.name, 40)}
                              </div>
                              {loadingFileId === file.docId && (
                                <div className="text-gray-500 dark:text-gray-400 text-xs mt-1">
                                  Loading content...
                                </div>
                              )}
                            </div>
                          </button>
                        ))}
                      {availableFiles.filter(f => f.type === 'file' && f.docId && !documentsInContext.some(existing => existing.id === f.docId)).length === 0 && (
                        <div className="px-3 py-2 text-xs text-gray-500 dark:text-gray-400">
                          All available documents are already in context
                        </div>
                      )}
                    </>
                  )}
                </div>
              </div>
            )}
          </div>
      </div>
      
      {/* Document pills - separate row to prevent overflow */}
      <div className="flex flex-wrap items-center gap-2 min-w-0">
        {documentsInContext.map((doc) => (
          <div
            key={doc.id}
            className="flex items-center gap-1 px-2 py-1 bg-accent text-accent-foreground rounded-full text-xs border border-accent/50 min-w-0 flex-shrink max-w-[200px]"
          >
            <span className="truncate min-w-0" title={doc.title}>
              {getTruncatedTitle(doc.title)}
            </span>
            <button
              onClick={() => handleRemoveDocument(doc.id)}
              className="flex-shrink-0 hover:bg-accent/80 rounded-full p-0.5 transition-colors"
              title={`Remove "${doc.title}"`}
            >
              <FiX size={10} />
            </button>
          </div>
        ))}
        
        {/* Empty state */}
        {documentsInContext.length === 0 && (
          <span className="text-xs text-muted-foreground italic">
            No documents in context
          </span>
        )}
      </div>
    </div>
  );
}