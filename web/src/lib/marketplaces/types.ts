import * as yup from "yup";

// Matches server/features/skill/marketplace_models.py and skills/marketplace/models.py.
const identifier = yup.string().uuid().defined();
const sharePermission = yup
  .string<"VIEWER" | "EDITOR">()
  .oneOf(["VIEWER", "EDITOR"])
  .defined();
const installationPolicy = yup
  .string<"AVAILABLE" | "DEFAULT" | "REQUIRED" | "NOT_AVAILABLE">()
  .oneOf(["AVAILABLE", "DEFAULT", "REQUIRED", "NOT_AVAILABLE"])
  .defined();

export const marketplaceSourceSchema = yup
  .object({
    provider: yup.string<"github">().oneOf(["github"]).defined(),
    provider_config: yup
      .object({
        owner: yup.string().required(),
        repo: yup.string().required(),
        ref: yup.string().required(),
        folder: yup.string().nullable().defined(),
      })
      .defined(),
    personal: yup.boolean().defined(),
  })
  .defined();

export type MarketplaceSource = yup.InferType<typeof marketplaceSourceSchema>;
export type MarketplaceCreate = Omit<MarketplaceSource, "personal"> & {
  name: string;
} & (
    | { personal: true; access?: never }
    | { personal: false; access?: MarketplaceAccessUpdate }
  );

export const retirementProposalSchema = yup
  .object({
    revision: yup.string().required(),
    skill_ids: yup.array(identifier).defined(),
    approved: yup.boolean().defined(),
  })
  .defined();

export type RetirementProposal = yup.InferType<typeof retirementProposalSchema>;
export type RetirementConfirmation = Pick<
  RetirementProposal,
  "revision" | "skill_ids"
>;

const blockedEntries = yup
  .mixed<Record<string, string>>(
    (value: unknown): value is Record<string, string> =>
      typeof value === "object" &&
      value !== null &&
      !Array.isArray(value) &&
      Object.values(value).every((reason) => typeof reason === "string")
  )
  .defined();

export const marketplaceSchema = yup
  .object({
    id: identifier,
    name: yup.string().defined(),
    provider: marketplaceSourceSchema.fields.provider,
    provider_config: marketplaceSourceSchema.fields.provider_config,
    owner_user_id: identifier.nullable(),
    login_user_id: identifier.nullable(),
    public_permission: sharePermission.nullable(),
    installation_policy: installationPolicy,
    group_shares: yup
      .array(
        yup.object({
          user_group_id: yup.number().integer().defined(),
          permission: sharePermission,
          installation_policy: installationPolicy.nullable(),
        })
      )
      .defined(),
    sync_requested: yup.boolean().defined(),
    sync_pending: yup.boolean().defined(),
    sync_status: yup
      .string<"applied" | "failed" | "needs_confirmation">()
      .oneOf(["applied", "failed", "needs_confirmation"])
      .nullable()
      .defined(),
    last_synced_revision: yup.string().nullable().defined(),
    last_synced_at: yup.string().nullable().defined(),
    last_error: yup.string().nullable().defined(),
    blocked_entries: blockedEntries,
    retirement_proposal: retirementProposalSchema.nullable(),
    live_skill_count: yup.number().integer().min(0).defined(),
    retired_skill_count: yup.number().integer().min(0).defined(),
  })
  .defined();

export type Marketplace = yup.InferType<typeof marketplaceSchema>;

export const marketplaceDetailSchema = yup
  .object({
    marketplace: marketplaceSchema,
    skills: yup
      .array(
        yup.object({
          id: identifier,
          name: yup.string().defined(),
          current_version_id: identifier.nullable(),
          retired_at: yup.string().nullable().defined(),
          follows_marketplace_access: yup.boolean().defined(),
        })
      )
      .defined(),
  })
  .defined();

export type MarketplaceDetail = yup.InferType<typeof marketplaceDetailSchema>;

const readyEntry = yup.object({
  status: yup.string<"ok">().oneOf(["ok"]).defined(),
  entry_key: yup.string().defined(),
  path: yup.string().defined(),
  name: yup.string().defined(),
  description: yup.string().defined(),
});
const blockedEntry = yup.object({
  status: yup.string<"blocked">().oneOf(["blocked"]).defined(),
  entry_key: yup.string().defined(),
  path: yup.string().defined(),
  reason: yup.string().defined(),
});
const unsupportedEntry = yup.object({
  status: yup.string<"not_supported">().oneOf(["not_supported"]).defined(),
  entry_key: yup.string().defined(),
  reason: yup.string().defined(),
});
const statusSchema = yup.object({ status: yup.string().defined() });
// oxlint-disable-next-line anti-slop/no-unknown-parameters -- Select the schema while parsing untrusted preview JSON.
const previewEntrySchema = yup.lazy((value: unknown) => {
  const { status } = statusSchema.validateSync(value, { strict: true });
  switch (status) {
    case "ok":
      return readyEntry;
    case "blocked":
      return blockedEntry;
    default:
      return unsupportedEntry;
  }
});

const completePreview = yup.object({
  status: yup.string<"complete">().oneOf(["complete"]).defined(),
  revision: yup.string().required(),
  entries: yup.array(previewEntrySchema).defined(),
});
const failedPreview = yup.object({
  status: yup.string<"failed">().oneOf(["failed"]).defined(),
  revision: yup.string().required(),
  reason: yup.string().defined(),
});
// oxlint-disable-next-line anti-slop/no-unknown-parameters -- Validate the response variant at the API boundary.
export const marketplacePreviewSchema = yup.lazy((value: unknown) =>
  statusSchema.validateSync(value, { strict: true }).status === "complete"
    ? completePreview
    : failedPreview
);
export type MarketplacePreview = yup.InferType<typeof marketplacePreviewSchema>;

export interface MarketplaceAccessUpdate {
  public_permission?: Marketplace["public_permission"];
  installation_policy?: Marketplace["installation_policy"];
  group_shares?: {
    group_id: number;
    permission: "VIEWER" | "EDITOR";
    installation_policy?: Marketplace["installation_policy"] | null;
  }[];
}
