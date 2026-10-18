import type { ReactNode } from "react";
import PluginsPage from "@/views/admin/PluginsPage";

export default function PluginsLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <PluginsPage />
      {children}
    </>
  );
}
