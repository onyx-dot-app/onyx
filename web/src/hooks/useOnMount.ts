"use client";

import { useEffect, useState } from "react";

/**
 * Hook that tracks whether the component has mounted on the client.
 *
 * Useful for avoiding hydration mismatches in SSR/SSG environments where
 * certain browser-only APIs (e.g., `window`, `localStorage`) are unavailable
 * on the server. By checking `isMounted`, you can defer rendering of
 * client-only content until after hydration.
 *
 * @param f - Optional callback to execute once on mount. This allows you to
 *            run initialization logic (e.g., setting up event listeners,
 *            fetching initial data) without needing a separate `useEffect`
 *            in the consuming component.
 * @returns `true` after the component has mounted, `false` during SSR and
 *          initial render.
 *
 * @example
 * ```tsx
 * function MyComponent() {
 *   const isMounted = useOnMount(() => {
 *     console.log("Component mounted!");
 *   });
 *
 *   if (!isMounted) return null; // or a loading skeleton
 *
 *   return <div>Client-only content using window.innerWidth</div>;
 * }
 * ```
 */
export default function useOnMount(f?: React.EffectCallback): boolean {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    return f?.();
  }, []);

  return mounted;
}
