import { getAuthTypeMetadataSS, logoutSS } from "@/lib/userSS";
import { NextRequest } from "next/server";

export const POST = async (request: NextRequest) => {
  // Directs the logout request to the appropriate FastAPI endpoint.
  // Needed since env variables don't work well on the client-side
  const authTypeMetadata = await getAuthTypeMetadataSS();
  const response = await logoutSS(authTypeMetadata.authType, request.headers);

  if (response && !response.ok) {
    return new Response(response.body, { status: response?.status });
  }

  // Always clear the auth cookie on logout. This is critical for the JWT
  // auth backend where destroy_token is a no-op (stateless), but is also
  // the correct thing to do for Redis/Postgres backends — the server-side
  // Set-Cookie from FastAPI never reaches the browser since logoutSS is a
  // server-to-server fetch.
  const cookiesToDelete = ["fastapiusersauth"];
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
