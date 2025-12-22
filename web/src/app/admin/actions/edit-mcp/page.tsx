"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import type { Route } from "next";

export default function EditMCPPage() {
  const router = useRouter();

  useEffect(() => {
    // Redirect to MCP actions page
    router.replace("/admin/actions/mcp" as Route);
  }, [router]);

  return null;
}
