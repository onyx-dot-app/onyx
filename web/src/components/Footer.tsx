"use client";

import React from "react";

interface FooterProps {
  footerHtml:string
}

export const Footer: React.FC<FooterProps> = ({footerHtml}) => {
  return (
  <footer className="border-b border-border bg-background-emphasis">
    <div className="mx-8 flex h-16-auto" dangerouslySetInnerHTML={{ __html: footerHtml }}>
    </div>
  </footer>
  )
};
