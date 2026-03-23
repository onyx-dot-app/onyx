import { cookies } from "next/headers";
import { AUTH_ERROR_COOKIE } from "@/app/auth/lib";
import AuthErrorContent from "./AuthErrorContent";

async function Page() {
  const cookieStore = await cookies();
  const errorMessage = cookieStore.get(AUTH_ERROR_COOKIE)?.value || null;

  return <AuthErrorContent message={errorMessage} />;
}

export default Page;
