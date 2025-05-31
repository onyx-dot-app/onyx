'use client';

import React from 'react';
import { Logo } from '@/components/logo/Logo';
import { UserDropdown } from '@/components/UserDropdown';
import { DocumentSidebar } from '@/components/documents/DocumentSidebar';
import { DocumentChatSidebar } from '@/components/documents/DocumentChatSidebar';
import { defaultSidebarFiles } from '@/lib/documents/types';

interface DocumentLayoutProps {
  children: React.ReactNode;
}

export function DocumentLayout({ children }: DocumentLayoutProps) {
  const chatSidebarWidth = 350;

  return (
    <div className="relative min-h-screen bg-background">
      {/* User Dropdown in top right */}
      <div className="fixed top-3 right-4 z-40">
        <UserDropdown page="documents" />
      </div>
      
      {/* Main content with sidebars */}
      <div className="flex h-screen">
        {/* Left Sidebar with Logo */}
        <div className="flex-none w-[250px] flex flex-col border-r border-border bg-background-sidebar dark:bg-[#000] dark:border-none">
          {/* Logo at top of sidebar */}
          <div className="p-4 flex items-center">
            <Logo height={24} width={24} />
            <span className="ml-2 font-semibold text-lg">Valkai</span>
          </div>
          
          {/* Sidebar content */}
          <div className="flex-grow overflow-y-auto">
            <DocumentSidebar files={defaultSidebarFiles} />
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
          />
        </div>
      </div>
    </div>
  );
}
