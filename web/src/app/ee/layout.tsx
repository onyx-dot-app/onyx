import { SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED } from "@/lib/constants";
import { fetchStandardSettingsSS } from "@/components/settings/lib";

export default async function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // First check build-time constant (fast path)
  if (!SERVER_SIDE_ONLY__PAID_ENTERPRISE_FEATURES_ENABLED) {
    return (
      <div className="flex h-screen">
        <div className="mx-auto my-auto text-lg font-bold text-red-500">
          This functionality is only available in the Enterprise Edition :(
        </div>
      </div>
    );
  }

  // Then check runtime license status (for license enforcement mode)
  // This allows gating EE features when user doesn't have a valid license
  try {
    const settingsResponse = await fetchStandardSettingsSS();
    if (settingsResponse?.ok) {
      const settings = await settingsResponse.json();
      if (settings.ee_features_enabled === false) {
        return (
          <div className="flex h-screen">
            <div className="mx-auto my-auto text-lg font-bold text-red-500">
              This functionality requires an active Enterprise license.
            </div>
          </div>
        );
      }
    }
  } catch (error) {
    // If settings fetch fails, allow access (fail open for better UX)
    console.error("Failed to fetch settings for EE check:", error);
  }

  return children;
}
