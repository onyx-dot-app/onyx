// Catalog of `{{user.<key>}}` placeholders an agent author can insert into the
// Instructions / Reminders prompts. At chat time the backend substitutes each
// with the current user's IdP directory attribute (or basic identity).
// MUST stay in sync with the backend allow-list (enforced by
// backend/tests/unit/onyx/prompts/test_prompt_utils.py):
//   - onyx/prompts/prompt_utils.py `USER_PLACEHOLDER_KEYS`
//   - onyx/auth/oauth_claims_capture.py `_PROFILE_FIELDS`

export interface UserPlaceholder {
  key: string;
  label: string;
}

// Directory profile fields sourced from the IdP login snapshot.
export const USER_DIRECTORY_PLACEHOLDERS: UserPlaceholder[] = [
  { key: "department", label: "Department" },
  { key: "job_title", label: "Job title" },
  { key: "city", label: "City" },
  { key: "state", label: "State" },
  { key: "country", label: "Country" },
  { key: "office_location", label: "Office location" },
  { key: "usage_location", label: "Usage location" },
  { key: "company_name", label: "Company" },
  { key: "preferred_language", label: "Preferred language" },
  { key: "timezone", label: "Timezone" },
];

// Basic identity fields sourced from the user record.
export const USER_IDENTITY_PLACEHOLDERS: UserPlaceholder[] = [
  { key: "email", label: "Email" },
  { key: "name", label: "Name" },
  { key: "role", label: "Role" },
];

export const USER_PLACEHOLDERS: UserPlaceholder[] = [
  ...USER_DIRECTORY_PLACEHOLDERS,
  ...USER_IDENTITY_PLACEHOLDERS,
];

// The token inserted into the prompt for a given placeholder key.
export function userPlaceholderToken(key: string): string {
  return `{{user.${key}}}`;
}
