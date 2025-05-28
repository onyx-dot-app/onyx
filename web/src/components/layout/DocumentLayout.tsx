'use client';

import React from 'react';
import { Logo } from '@/components/logo/Logo';
import { UserDropdown } from '@/components/UserDropdown';
import { DocumentSidebar } from '@/components/documents/DocumentSidebar';
import { defaultSidebarFiles } from '@/lib/documents/types';

interface DocumentLayoutProps {
  children: React.ReactNode;
}

export function DocumentLayout({ children }: DocumentLayoutProps) {
  return (
    <div className="relative min-h-screen bg-background">
      {/* User Dropdown in top right */}
      <div className="fixed top-3 right-4 z-40">
        <UserDropdown page="documents" />
      </div>
      
      {/* Main content with sidebar */}
      <div className="flex h-screen">
        {/* Sidebar with Logo */}
        <div className="flex-none w-[250px] flex flex-col">
          {/* Logo at top of sidebar */}
          <div className="p-4 flex items-center border-b border-border">
            <Logo height={24} width={24} />
            <span className="ml-2 font-semibold text-lg">onyx</span>
          </div>
          
          {/* Sidebar content */}
          <div className="flex-grow overflow-y-auto">
            <DocumentSidebar files={defaultSidebarFiles} />
          </div>
        </div>
        
        {/* Content */}
        <div className="flex-grow overflow-auto">
          {children}
        </div>
      </div>
    </div>
  );
}
