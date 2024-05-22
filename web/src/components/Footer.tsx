"use client";

import React from "react";

interface FooterProps {
  eea_config:any
}

export const Footer: React.FC<FooterProps> = ({eea_config}) => {
  const footer_html_default = '<a class="py-4" href="https://Danswer.ai" target="_blank"><div class="flex"><div class="h-[32px] w-[30px]"><Image src="/logo.png" alt="Logo" width="1419" height="1520" /></div><h3 class="flex text-l text-strong my-auto">&nbsp;Powered by Danswer.ai</h3></div></a>'
  let footer_html = footer_html_default;
  if (eea_config?.config !== undefined){
    const config = JSON.parse(eea_config?.config);
    footer_html = config?.footer?.footer_html || footer_html_default;
  }
  return (
  <footer className="border-b border-border bg-background-emphasis">
    <div className="mx-8 flex h-16" dangerouslySetInnerHTML={{ __html: footer_html }}>
    </div>
  </footer>
  )
};
