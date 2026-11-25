import { usePathname } from "@opal/navigation";
import type { CustomizePanel } from "@/lib/customize/paths";

/** The panel that the current page sits in. */
export function usePanel(): CustomizePanel {
  return usePathname().startsWith("/admin") ? "admin" : "customize";
}
