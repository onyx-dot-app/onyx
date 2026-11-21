// Minimal next/navigation surface so Opal's navigation layer runs outside Next.js.
// Local desktop windows are single pages, so routing reduces to plain location changes.
export type ReadonlyURLSearchParams = URLSearchParams;

export enum RedirectType {
  push = "push",
  replace = "replace",
}

interface NavigateOptions {
  scroll?: boolean;
}

export interface AppRouterLike {
  push: (href: string, options?: NavigateOptions) => void;
  replace: (href: string, options?: NavigateOptions) => void;
  back: () => void;
  forward: () => void;
  refresh: () => void;
  prefetch: (href: string) => void;
}

const router: AppRouterLike = {
  push: (href) => window.location.assign(href),
  replace: (href) => window.location.replace(href),
  back: () => window.history.back(),
  forward: () => window.history.forward(),
  refresh: () => window.location.reload(),
  prefetch: () => undefined,
};

export function useRouter(): AppRouterLike {
  return router;
}

export function usePathname(): string {
  return window.location.pathname;
}

export function useSearchParams(): ReadonlyURLSearchParams {
  return new URLSearchParams(window.location.search);
}

export function useParams(): Record<string, string> {
  return {};
}

export function useSelectedLayoutSegment(): string | null {
  return null;
}

export function useSelectedLayoutSegments(): string[] {
  return [];
}

export function redirect(href: string, type: RedirectType = RedirectType.replace): never {
  if (type === RedirectType.push) window.location.assign(href);
  else window.location.replace(href);
  throw new Error(`redirect to ${href}`);
}

export function permanentRedirect(href: string): never {
  return redirect(href, RedirectType.replace);
}

export function notFound(): never {
  throw new Error("not found");
}
