import { DesktopOAuthHandoff } from "@/sections/oauth/DesktopOAuthHandoff";

// The proxy rewrites desktop callbacks here, ahead of any auth-guarded layout.
export default function DesktopOAuthHandoffPage() {
  return <DesktopOAuthHandoff />;
}
