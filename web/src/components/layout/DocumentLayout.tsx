'use client';

import React, { useState, useCallback } from 'react';
import { Logo } from '@/components/logo/Logo';
import { UserDropdown } from '@/components/UserDropdown';
import { DocumentSidebar } from '@/components/documents/DocumentSidebar';
import { DocumentChatSidebar } from '@/components/documents/DocumentChatSidebar';
import { getSidebarFiles, DocumentConfig } from '@/lib/documents/types';

interface DocumentLayoutProps {
  children: React.ReactNode;
  documentContent?: string;
  documentType?: 'document' | 'spreadsheet';
  documentTitle?: string;
  setContent?: (content: string) => void;
  documentConfig?: DocumentConfig;
}

export function DocumentLayout({ 
  children,
  documentContent = '',
  documentType = 'document',
  documentTitle = '',
  setContent,
  documentConfig
}: DocumentLayoutProps) {
  const chatSidebarWidth = 350;
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  
  const toggleSidebar = useCallback(() => {
    setSidebarCollapsed(prev => !prev);
  }, []);

  return (
    <div className="relative min-h-screen bg-background">
      {/* User Dropdown in top right */}
      <div className="fixed top-3 right-4 z-40">
        <UserDropdown page="documents" />
      </div>
      
      {/* Main content with sidebars */}
      <div className="flex h-screen">
        {/* Left Sidebar with Logo */}
        <div 
          className={`flex-none flex flex-col border-r border-border bg-background-sidebar dark:bg-[#000] dark:border-none transition-all duration-300 ease-in-out ${sidebarCollapsed ? 'w-[60px]' : 'w-[250px]'}`}>
          {/* Logo at top of sidebar */}
          <div className="p-4 flex items-center relative">
            <div className="flex items-center">
              <div className="flex-shrink-0">
                <Logo height={24} width={24} />
              </div>
              <span className={`ml-2 font-semibold text-lg transition-opacity duration-200 ${sidebarCollapsed ? 'opacity-0 w-0 overflow-hidden' : 'opacity-100'}`}>Valkai</span>
            </div>
            
            {/* Toggle Button - positioned half on half off the sidebar edge */}
            <div 
              className="absolute h-full flex items-center top-0"
              style={{ right: '-12px', zIndex: 20 }}
            >
              <button
                onClick={toggleSidebar}
                className="flex items-center justify-center bg-background-sidebar dark:bg-[#000] border border-border dark:border-gray-800 rounded-full w-6 h-6 hover:bg-gray-200 dark:hover:bg-gray-800 shadow-sm"
                aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
              >
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  className={`h-3.5 w-3.5 text-gray-500 transition-transform duration-200 ${sidebarCollapsed ? 'rotate-180' : ''}`}
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                </svg>
              </button>
            </div>
          </div>
          
          {/* Sidebar content */}
          <div className="flex-grow overflow-y-auto">
            <DocumentSidebar files={getSidebarFiles(documentConfig)} collapsed={sidebarCollapsed} />
          </div>
        </div>
        
        {/* Content */}
        <div 
          className="flex-grow overflow-auto"
          style={{ 
            marginRight: `${chatSidebarWidth}px` 
          }}
        >
          {children}
        </div>

        {/* Right Chat Sidebar - Always visible */}
        <div 
          className="fixed right-0 top-0 h-full z-30"
          style={{ width: `${chatSidebarWidth}px` }}
        >
          <DocumentChatSidebar
            initialWidth={chatSidebarWidth}
            documentContent={documentContent}
            documentType={documentType}
            documentTitle={documentTitle}
            setContent={setContent}
          />
        </div>
      </div>
    </div>
  );
}
