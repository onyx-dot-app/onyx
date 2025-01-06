"use client";

import React, { createContext, useContext, useState, useEffect } from "react";
import { User, UserRole } from "@/lib/types";
import { getCurrentUser } from "@/lib/user";
import { usePostHog } from "posthog-js/react";

interface UserContextType {
  user: User | null;
  isAdmin: boolean;
  isCurator: boolean;
  refreshUser: () => Promise<void>;
  isCloudSuperuser: boolean;
  updateUserAutoScroll: (autoScroll: boolean | null) => Promise<void>;
}

const UserContext = createContext<UserContextType | undefined>(undefined);

export function UserProvider({
  children,
  user,
}: {
  children: React.ReactNode;
  user: User | null;
}) {
  const [upToDateUser, setUpToDateUser] = useState<User | null>(user);

  const posthog = usePostHog();

  useEffect(() => {
    if (!posthog) return;

    if (user?.id) {
      const identifyData: Record<string, any> = {
        email: user.email,
      };
      if (user.organization_name) {
        identifyData.organization_name = user.organization_name;
      }
      posthog.identify(user.id, identifyData);
    } else {
      posthog.reset();
    }
  }, [posthog, user]);

  const fetchUser = async () => {
    try {
      const currentUser = await getCurrentUser();
      setUpToDateUser(currentUser);
    } catch (error) {
      console.error("Error fetching current user:", error);
    }
  };
  const updateUserAutoScroll = async (autoScroll: boolean | null) => {
    try {
      const response = await fetch("/api/auto-scroll", {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ auto_scroll: autoScroll }),
      });
      setUpToDateUser((prevUser) => {
        if (prevUser) {
          return {
            ...prevUser,
            preferences: {
              ...prevUser.preferences,
              auto_scroll: autoScroll,
            },
          };
        }
        return prevUser;
      });

      if (!response.ok) {
        throw new Error("Failed to update auto-scroll setting");
      }
    } catch (error) {
      console.error("Error updating auto-scroll setting:", error);
      throw error;
    }
  };

  const refreshUser = async () => {
    await fetchUser();
  };

  return (
    <UserContext.Provider
      value={{
        user: upToDateUser,
        refreshUser,
        updateUserAutoScroll,
        isAdmin: upToDateUser?.role === UserRole.ADMIN,
        // Curator status applies for either global or basic curator
        isCurator:
          upToDateUser?.role === UserRole.CURATOR ||
          upToDateUser?.role === UserRole.GLOBAL_CURATOR,
        isCloudSuperuser: upToDateUser?.is_cloud_superuser ?? false,
      }}
    >
      {children}
    </UserContext.Provider>
  );
}

export function useUser() {
  const context = useContext(UserContext);
  if (context === undefined) {
    throw new Error("useUser must be used within a UserProvider");
  }
  return context;
}
