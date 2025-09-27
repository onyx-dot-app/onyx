import { User, UserRole } from "@/lib/types";

// Constants from backend
const API_KEY_EMAIL_DOMAIN = "onyxapikey.ai";

/**
 * Check if a user is a Slack user
 */
export function isSlackUser(user: User): boolean {
  return user.role === UserRole.SLACK_USER;
}

/**
 * Check if a user is an API key (identified by email domain)
 */
export function isApiKeyUser(user: User): boolean {
  return user.email.endsWith(API_KEY_EMAIL_DOMAIN);
}

/**
 * Get display name for API key users
 */
export function getDisplayEmail(email: string): string {
  if (email.endsWith(API_KEY_EMAIL_DOMAIN)) {
    const name = email.split("@")[0];
    if (!name) return email;
    if (name === "API_KEY__Unnamed API Key") {
      return "Unnamed API Key";
    }
    return name.replace("API_KEY__", "API Key: ");
  }
  return email;
}

export type UserTypeFilter = {
  showSlackUsers: boolean;
  showApiKeys: boolean;
};

/**
 * Filter users based on type preferences
 */
export function filterUsersByType(users: User[], filters: UserTypeFilter): User[] {
  return users.filter((user) => {
    if (isSlackUser(user) && !filters.showSlackUsers) {
      return false;
    }
    if (isApiKeyUser(user) && !filters.showApiKeys) {
      return false;
    }
    return true;
  });
}

/**
 * Get user type label for display
 */
export function getUserTypeLabel(user: User): string | null {
  if (isSlackUser(user)) {
    return "Slack User";
  }
  if (isApiKeyUser(user)) {
    return "API Key";
  }
  return null;
}