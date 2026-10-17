import type { ReactNode } from "react";
import PluginsPage from "@/sections/plugins/PluginsPage";

export default function PluginsLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <PluginsPage />
      {children}
    </>
  );
}
