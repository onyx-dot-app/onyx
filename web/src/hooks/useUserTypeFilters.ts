"use client";

import { useState, useEffect, useMemo } from "react";
import { User } from "@/lib/types";
import { 
  UserTypeFilter, 
  filterUsersByType, 
  isSlackUser, 
  isApiKeyUser 
} from "@/lib/userUtils";

const STORAGE_KEY = "admin-user-type-filters";

const DEFAULT_FILTERS: UserTypeFilter = {
  showSlackUsers: true,
  showApiKeys: true,
};

/**
 * Custom hook to manage user type filters with localStorage persistence
 */
export function useUserTypeFilters(users: User[] = []) {
  const [filters, setFilters] = useState<UserTypeFilter>(DEFAULT_FILTERS);

  // Load filters from localStorage on mount
  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        const parsedFilters = JSON.parse(stored);
        setFilters({
          showSlackUsers: parsedFilters.showSlackUsers ?? true,
          showApiKeys: parsedFilters.showApiKeys ?? true,
        });
      }
    } catch (error) {
      console.warn("Failed to load user type filters from localStorage:", error);
    }
  }, []);

  // Save filters to localStorage whenever they change
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(filters));
    } catch (error) {
      console.warn("Failed to save user type filters to localStorage:", error);
    }
  }, [filters]);

  // Calculate user counts and filtered users
  const { filteredUsers, userCounts } = useMemo(() => {
    const slackUsers = users.filter(isSlackUser).length;
    const apiKeys = users.filter(isApiKeyUser).length;
    const totalUsers = users.length;

    const filtered = filterUsersByType(users, filters);

    return {
      filteredUsers: filtered,
      userCounts: {
        slackUsers,
        apiKeys,
        totalUsers,
      },
    };
  }, [users, filters]);

  return {
    filters,
    setFilters,
    filteredUsers,
    userCounts,
  };
}