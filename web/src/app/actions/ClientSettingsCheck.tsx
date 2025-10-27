"use client";

import { useSettingsContext } from "@/components/settings/SettingsProvider";
import { User, UserRole } from "@/lib/types";

export default function ClientSettingsCheck({
  user,
  children,
}: {
  user: User | null;
  children: React.ReactNode;
}) {
  const settings = useSettingsContext();

  if (
    user?.role !== UserRole.ADMIN &&
    settings?.settings?.all_users_actions_creation_enabled === false
  ) {
    return (
      <div className="w-full h-screen flex flex-col items-center justify-center bg-background text-center">
        <h1 className="text-2xl font-semibold text-red-500 mb-4">
          Account Disabled
        </h1>
        <p className="text-muted-foreground max-w-md">
          Your account has been disabled or you don't have permission to create
          actions. Please contact the administrator to restore access.
        </p>
      </div>
    );
  }

  return <>{children}</>;
}
