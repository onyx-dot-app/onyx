import { cookies } from "next/headers";
import { User } from "@/lib/types";
import { buildUrl } from "@/lib/utilsSS";
import { ReadonlyRequestCookies } from "next/dist/server/web/spec-extension/adapters/request-cookies";
import { SERVER_SIDE_ONLY__AUTH_COOKIE_NAME } from "@/lib/constants";

export async function getCurrentUserSS(): Promise<User | null> {
  try {
    const cookieString = processCookies(await cookies());

    const response = await fetch(buildUrl("/me"), {
      credentials: "include",
      next: { revalidate: 0 },
      headers: { cookie: cookieString },
    });

    if (!response.ok) return null;

    const user = await response.json();
    return user;
  } catch (e) {
    console.log(`Error fetching user: ${e}`);
    return null;
  }
}

export function processCookies(cookies: ReadonlyRequestCookies): string {
  let cookieString = cookies
    .getAll()
    .map((cookie) => `${cookie.name}=${cookie.value}`)
    .join("; ");

  // Inject debug auth cookie for local development against remote backend (only if not already present)
  if (process.env.DEBUG_AUTH_COOKIE && process.env.NODE_ENV === "development") {
    const hasAuthCookie = cookieString
      .split(/;\s*/)
      .some((c) => c.startsWith(`${SERVER_SIDE_ONLY__AUTH_COOKIE_NAME}=`));
    if (!hasAuthCookie) {
      const debugCookie = `${SERVER_SIDE_ONLY__AUTH_COOKIE_NAME}=${process.env.DEBUG_AUTH_COOKIE}`;
      cookieString = cookieString
        ? `${cookieString}; ${debugCookie}`
        : debugCookie;
    }
  }

  return cookieString;
}
