import { redirect } from "next/navigation";
import { getCurrentUserSS, getAuthTypeMetadataSS } from "@/lib/userSS";
import { UserRole } from "@/lib/types";

export async function AuthLayout({ children }: { children: React.ReactNode }) {
  const [authMeta, user] = await Promise.all([
    getAuthTypeMetadataSS(),
    getCurrentUserSS(),
  ]);

  if (authMeta?.authType !== "disabled") {
    if (!user) return redirect("/auth/login");
    if (user.role === UserRole.BASIC) return redirect("/chat");
    if (!user.is_verified && authMeta?.requiresVerification)
      return redirect("/auth/waiting-on-verification");
  }

  return <>{children}</>;
}
