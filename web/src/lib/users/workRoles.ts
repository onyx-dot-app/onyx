// Work roles that the profile settings offer, stored in `personalization.role`.
// `value` is the stored text and never changes; `labelKey` selects the
// translated label under `profile.workRole`. The backend accepts any text, so
// a stored role that is not a `value` here shows as "Other" with its text.
export const WORK_ROLE_OPTIONS = [
  { value: "Engineering", labelKey: "engineering" },
  { value: "Product", labelKey: "product" },
  { value: "Design", labelKey: "design" },
  { value: "Data & Analytics", labelKey: "dataAnalytics" },
  { value: "Sales", labelKey: "sales" },
  { value: "Marketing", labelKey: "marketing" },
  { value: "Customer Support & Success", labelKey: "customerSupportSuccess" },
  { value: "Operations", labelKey: "operations" },
  { value: "Finance", labelKey: "finance" },
  { value: "People & HR", labelKey: "peopleHr" },
  { value: "Legal", labelKey: "legal" },
  { value: "Leadership", labelKey: "leadership" },
] as const;

export const WORK_ROLE_VALUES: ReadonlySet<string> = new Set(
  WORK_ROLE_OPTIONS.map((option) => option.value)
);
