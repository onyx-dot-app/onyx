import { StrictMode, type ReactElement } from "react";
import { createRoot } from "react-dom/client";
import { TooltipProvider } from "@radix-ui/react-tooltip";
import "@/styles.css";

// Opal's Button renders a Radix Tooltip, which needs the provider above it.
export function mount(element: ReactElement, bodyClass?: string): void {
  // Follow the system appearance live, as native windows do.
  const scheme = window.matchMedia("(prefers-color-scheme: dark)");
  const applyScheme = () =>
    document.documentElement.classList.toggle("dark", scheme.matches);
  applyScheme();
  scheme.addEventListener("change", applyScheme);
  if (bodyClass) document.body.classList.add(bodyClass);
  const container = document.getElementById("root");
  if (!container) throw new Error("missing #root");
  createRoot(container).render(
    <StrictMode>
      <TooltipProvider>{element}</TooltipProvider>
    </StrictMode>
  );
}
