export const WORK_AREA_OPTIONS = [
  { value: "engineering", label: "Engineering" },
  { value: "product", label: "Product" },
  { value: "executive", label: "Executive" },
  { value: "sales", label: "Sales" },
  { value: "marketing", label: "Marketing" },
  { value: "other", label: "Other" },
];

export const LEVEL_OPTIONS = [
  { value: "ic", label: "IC" },
  { value: "manager", label: "Manager" },
];

export const WORK_AREAS_WITH_LEVEL = ["engineering", "product", "sales"];

export const BUILD_USER_PERSONA_COOKIE_NAME = "build_user_persona";

// Helper type for the consolidated cookie
export interface BuildUserPersona {
  workArea: string;
  level?: string;
}

// Helper functions for getting/setting the consolidated cookie
export function getBuildUserPersona(): BuildUserPersona | null {
  if (typeof window === "undefined") return null;

  const cookieValue = document.cookie
    .split("; ")
    .find((row) => row.startsWith(`${BUILD_USER_PERSONA_COOKIE_NAME}=`))
    ?.split("=")[1];

  if (!cookieValue) return null;

  try {
    return JSON.parse(decodeURIComponent(cookieValue));
  } catch {
    return null;
  }
}

export function setBuildUserPersona(persona: BuildUserPersona): void {
  const cookieValue = encodeURIComponent(JSON.stringify(persona));
  const expires = new Date();
  expires.setFullYear(expires.getFullYear() + 1);
  document.cookie = `${BUILD_USER_PERSONA_COOKIE_NAME}=${cookieValue}; path=/; expires=${expires.toUTCString()}`;
}
