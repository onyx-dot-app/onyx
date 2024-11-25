import { cookies } from "next/headers";
import { HOST_URL, INTERNAL_URL } from "./constants";

export function buildClientUrl(path: string) {
  if (path.startsWith("/")) {
    return `${HOST_URL}${path}`;
  }
  return `${HOST_URL}/${path}`;
}

export function buildUrl(path: string) {
  if (path.startsWith("/")) {
    return `${INTERNAL_URL}${path}`;
  }
  return `${INTERNAL_URL}/${path}`;
}

export async function fetchSS(url: string, options?: RequestInit) {
  const init = options || {
    credentials: "include",
    cache: "no-store",
    headers: {
      cookie: (await cookies())
        .getAll()
        .map((cookie) => `${cookie.name}=${cookie.value}`)
        .join("; "),
    },
  };
  return fetch(buildUrl(url), init);
}
