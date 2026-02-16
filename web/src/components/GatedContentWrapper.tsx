"use client";

import { usePathname } from "next/navigation";
import AccessRestrictedPage from "@/components/errorPages/AccessRestrictedPage";

// Paths accessible even when gated - allows users to manage billing updates and seat counts
const ALLOWED_GATED_PATHS = ["/admin/billing", "/admin/users"];

/**
 * Check if pathname matches an allowed path exactly or is a subpath.
 * Uses strict matching to prevent bypasses like "/admin/billing-foo".
 */
function isPathAllowed(pathname: string): boolean {
  return ALLOWED_GATED_PATHS.some(
    (allowedPath) =>
      pathname === allowedPath || pathname.startsWith(allowedPath + "/")
  );
}

export default function GatedContentWrapper({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();

  if (isPathAllowed(pathname)) {
    return <>{children}</>;
  }

  return <AccessRestrictedPage />;
}
