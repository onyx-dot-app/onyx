import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
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

  // Delete cookies only if cloud is enabled (jwt auth)
  if (NEXT_PUBLIC_CLOUD_ENABLED) {
    const cookiesToDelete = ["fastapiusersauth"];
    const cookieOptions = {
      path: "/",
      secure: process.env.NODE_ENV === "production",
      httpOnly: true,
      sameSite: "lax" as const,
    };

    // Logout successful, delete cookies
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
  } else {
    return new Response(null, { status: 204 });
  }
};
