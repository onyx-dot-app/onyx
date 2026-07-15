"use client";

import { AuthLayouts } from "@opal/layouts";
import { useAuthDocumentTitle } from "@/lib/app/hooks";

interface AuthChromeProps {
  children: React.ReactNode;
}

export default function AuthChrome({ children }: AuthChromeProps) {
  useAuthDocumentTitle();

  return <AuthLayouts.Root>{children}</AuthLayouts.Root>;
}
