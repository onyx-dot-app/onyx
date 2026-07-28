import { logoutSS } from "@/lib/auth/svcSS";
import { SERVER_SIDE_ONLY__AUTH_COOKIE_NAME } from "@/lib/constants";
import { NextRequest } from "next/server";

export const POST = async (request: NextRequest) => {
  // Proxies logout to the backend /auth/logout endpoint.
  // Needed since env variables don't work well on the client-side
  const response = await logoutSS(request.headers);

  if (response && !response.ok) {
    return new Response(response.body, { status: response?.status });
  }

  // Always clear the auth cookie on logout. This is critical for the JWT
  // auth backend where destroy_token is a no-op (stateless), but is also
  // the correct thing to do for Redis/Postgres backends — the server-side
  // Set-Cookie from FastAPI never reaches the browser since logoutSS is a
  // server-to-server fetch.
  const cookiesToDelete = [SERVER_SIDE_ONLY__AUTH_COOKIE_NAME];
  const cookieOptions = {
    path: "/",
    secure: process.env.NODE_ENV === "production",
    httpOnly: true,
    sameSite: "lax" as const,
  };

  const headers = new Headers();

  cookiesToDelete.forEach((cookieName) => {
    headers.append(
      "Set-Cookie",
      `${cookieName}=; Max-Age=0; ${Object.entries(cookieOptions)
        .map(([key, value]) => `${key}=${value}`)
        .join("; ")}`
    );
  });

  return new Response(null, {
    status: 204,
    headers: headers,
  });
};
