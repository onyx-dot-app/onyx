import { logoutSS } from "@/lib/auth/svcSS";
import {
  NEXT_PUBLIC_AUTH_TYPE,
  SERVER_SIDE_ONLY__AUTH_COOKIE_NAME,
} from "@/lib/constants";
import { NextRequest } from "next/server";

export const POST = async (request: NextRequest) => {
  const response = await logoutSS(NEXT_PUBLIC_AUTH_TYPE, request.headers);

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
