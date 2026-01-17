"use client";

import { usePathname } from "next/navigation";
import AccessRestrictedPage from "@/components/errorPages/AccessRestrictedPage";

const ALLOWED_GATED_PATHS = ["/admin/billing", "/ee/admin/billing"];

export default function GatedContentWrapper({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const isAllowedPath = ALLOWED_GATED_PATHS.some((path) =>
    pathname.startsWith(path)
  );

  if (isAllowedPath) {
    return <>{children}</>;
  }

  return <AccessRestrictedPage />;
}
