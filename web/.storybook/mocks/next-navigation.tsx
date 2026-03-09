export function useRouter() {
  return {
    push: (_url: string) => {},
    replace: (_url: string) => {},
    back: () => {},
    forward: () => {},
    refresh: () => {},
    prefetch: (_url: string) => Promise.resolve(),
  };
}

export function usePathname() {
  return "/";
}

export function useSearchParams() {
  return new URLSearchParams() as ReadonlyURLSearchParams;
}

export function useParams() {
  return {};
}

export function redirect(_url: string) {}

export function notFound() {}
