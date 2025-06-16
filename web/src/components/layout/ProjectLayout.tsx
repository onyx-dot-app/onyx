'use client';

import React, { useState, useCallback } from 'react';
import { Logo } from '@/components/logo/Logo';
import { UserDropdown } from '@/components/UserDropdown';
import { DocumentSidebar } from '@/components/documents/DocumentSidebar';
import { DocumentChatSidebar } from '@/components/documents/DocumentChatSidebar';

interface ProjectLayoutProps {
  children: React.ReactNode;
  projectId: string;
  projectContent?: string;
  projectTitle?: string;
  setContent?: (content: string) => void;
}

export function ProjectLayout({ 
  children,
  projectId,
  projectContent = '',
  projectTitle = '',
  setContent
}: ProjectLayoutProps) {
  const chatSidebarWidth = 350;
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  
  const toggleSidebar = useCallback(() => {
    setSidebarCollapsed(prev => !prev);
  }, []);

  return (
    <div className="relative min-h-screen bg-background">
      {/* User Dropdown in top right */}
      <div className="fixed top-3 right-4 z-40">
        <UserDropdown page="projects" />
      </div>
      
      {/* Main content with sidebars */}
      <div className="flex h-screen">
        {/* Left Sidebar with Logo */}
        <div 
          className={`flex-none flex flex-col border-r border-border bg-background-sidebar dark:bg-[#000] dark:border-none transition-all duration-300 ease-in-out ${sidebarCollapsed ? 'w-[60px]' : 'w-[250px]'}`}>
          {/* Logo at top of sidebar */}
          <div className="p-4 flex items-center relative">
            <div className="flex items-center">
              <button
                onClick={toggleSidebar}
                className="flex items-center justify-center w-6 h-6 hover:bg-background-hover rounded transition-colors"
                title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
              >
                <div className={`transform transition-transform duration-200 ${sidebarCollapsed ? 'rotate-180' : ''}`}>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="15,18 9,12 15,6"></polyline>
                  </svg>
                </div>
              </button>
              {!sidebarCollapsed && (
                <div className="ml-2">
                  <Logo height={32} width={30} />
                </div>
              )}
            </div>
          </div>
          
          {/* Project Sidebar */}
          <div className="flex-1 overflow-hidden">
            <ProjectSidebar projectId={projectId} collapsed={sidebarCollapsed} />
          </div>
        </div>
        
        {/* Main Content Area */}
        <div className="flex-1 flex flex-col min-w-0">
          <main className="flex-1 overflow-auto">
            {children}
          </main>
        </div>
        
        {/* Right Chat Sidebar */}
        <div 
          className="flex-none border-l border-border bg-background-sidebar dark:bg-[#000] dark:border-none"
          style={{ width: `${chatSidebarWidth}px` }}
        >
          <DocumentChatSidebar 
            documentContent={projectContent}
            documentTitle={projectTitle}
            setContent={setContent}
            documentIds={[projectId]}
          />
        </div>
      </div>
    </div>
  );
}