'use client';

import React from 'react';
import FixedLogo from '@/components/logo/FixedLogo';
import { UserDropdown } from '@/components/UserDropdown';
import { DocumentSidebar } from '@/components/documents/DocumentSidebar';
import { defaultSidebarFiles } from '@/lib/documents/types';

interface DocumentLayoutProps {
  children: React.ReactNode;
}

export function DocumentLayout({ children }: DocumentLayoutProps) {
  return (
    <div className="relative min-h-screen bg-background">
      {/* Fixed Logo */}
      <FixedLogo backgroundToggled={false} />
      
      {/* User Dropdown in top right */}
      <div className="fixed top-3 right-4 z-40">
        <UserDropdown page="documents" />
      </div>
      
      {/* Main content with sidebar */}
      <div className="flex h-screen pt-16">
        {/* Sidebar */}
        <div className="flex-none w-[250px]">
          <DocumentSidebar files={defaultSidebarFiles} />
        </div>
        
        {/* Content */}
        <div className="flex-grow overflow-auto">
          {children}
        </div>
      </div>
    </div>
  );
}
