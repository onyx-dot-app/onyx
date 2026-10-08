import type { SWRResponse } from "swr";
import type { CredentialSpec } from "@/lib/credentials/types/spec";
import type { ValidSources } from "@/lib/connectors/types/source";
import type { TypedFile } from "@/lib/connectors/fileTypes";

/** The ways a credential can be created for a source. */
export enum CredentialCreationMethod {
  OAuth = "oauth",
  Manual = "manual",
}

export interface OAuthAdditionalKwargDescription {
  name: string;
  display_name: string;
  description: string;
}

export interface OAuthDetails {
  oauth_enabled: boolean;
  supports_manual_credentials: boolean;
  additional_kwargs: OAuthAdditionalKwargDescription[];
}

export interface CredentialBase<T> {
  credential_json: T;
  admin_public: boolean;
  source: ValidSources;
  name?: string;
  curator_public?: boolean;
  groups?: number[];
}

export interface CredentialWithPrivateKey<T> extends CredentialBase<T> {
  private_key: TypedFile;
}

export interface Credential<T> extends CredentialBase<T> {
  id: number;
  user_id: string | null;
  user_email: string | null;
  /** The creator's display name; null when they never set one. */
  user_personal_name: string | null;
  time_created: string;
  time_updated: string;
}

/**
 * A credential as the UI handles it, with no constraint on the shape of its
 * secret. Credential forms are built from per-source templates, so the call
 * sites that only list, pick or delete a credential never know that shape.
 */
export type AnyCredential = Credential<Record<string, unknown>>;

/** A connector that uses a credential. */
export interface CredentialUsage {
  cc_pair_id: number;
  cc_pair_name: string | null;
  connector_id: number;
  source: ValidSources;
}

/**
 * A credential from a source's credential list, with the connectors that use
 * it. `usages` holds only the connectors the current user can manage.
 */
export interface SimilarCredential extends AnyCredential {
  usages: CredentialUsage[];
}

/**
 * What `useSourceCredentials` returns: every credential the current admin
 * can see for one source.
 *
 * `data` is undefined until the first response lands. The endpoint filters
 * by permission, so each entry is the caller's to edit and delete.
 */
export type SourceCredentialsResult = SWRResponse<SimilarCredential[], Error>;

/**
 * Everything one source needs in order to be authenticated against, from
 * {@link useCredentialSetup}.
 *
 * The hook renders nothing and says nothing: every action resolves to an
 * error message or `null`, so each screen keeps its own copy and its own
 * choice of toast, banner or inline text.
 */
export interface CredentialSetup {
  /** The source's name for prose and labels, falling back to its key. */
  displayName: string;
  /** Every credential this admin can see. Undefined until the first load. */
  credentials: SimilarCredential[] | undefined;
  /**
   * Set when the credentials never loaded. A refresh that fails after a
   * success does not count, and neither do OAuth details that fail to load.
   */
  error: Error | undefined;
  /** The source's OAuth capabilities, once known. */
  oauthDetails: OAuthDetails | undefined;
  /**
   * True until the credentials have loaded and the OAuth details have either
   * loaded or failed; false once the credentials fail.
   */
  isLoading: boolean;
  /** The ways this source accepts a credential. */
  methods: CredentialCreationMethod[];
  /** True when there is more than one way in, so each needs naming. */
  namesMethods: boolean;
  /** The source's credential spec, null for a source with none. */
  spec: CredentialSpec | null;
  /** Whether this deployment offers the hosted Authorize flow for the source. */
  canAuthorize: boolean;
  /** The method whose creation form is showing, if any. */
  openMethod: CredentialCreationMethod | null;
  /**
   * Shows the creation form for one method. When a redirect is the whole
   * flow, leaves for the provider instead of opening anything.
   */
  open: (method: CredentialCreationMethod) => Promise<string | null>;
  /**
   * Shows one method's form without starting anything. `open` may leave for
   * the provider instead; this never does, so it is what a tab switch uses.
   */
  selectMethod: (method: CredentialCreationMethod) => void;
  /** Hides whichever creation form is showing. */
  close: () => void;
  /**
   * Deletes a credential, then refetches the list. Resolves to `null` only
   * on success; every failure resolves to a message, falling back to
   * `failureMessage` when the server sends none.
   */
  remove: (
    credential: AnyCredential,
    failureMessage: string
  ) => Promise<string | null>;
  /** Refetches the credential list. */
  refresh: () => void;
  /** Opens the hosted OAuth popup. `invalidUrlMessage` is the caller's copy. */
  authorize: (invalidUrlMessage: string) => Promise<string | null>;
  /** True while the popup request is in flight. */
  isAuthorizing: boolean;
}

/** One credential field a federated source asks for. */
export interface CredentialFieldSpec {
  type: string;
  description: string;
  required: boolean;
  default?: any;
  example?: any;
  secret: boolean;
}

/** The credential fields a federated source asks for. */
export interface CredentialSchemaResponse {
  credentials: Record<string, CredentialFieldSpec>;
}

/** Where a credential's stored capability check run stands. */
export type CredentialCheckRunStatus =
  | "running"
  | "completed"
  | "failed_to_run";

/**
 * One stored capability report. `connector_id` is null for the report on the
 * credential alone; `report` is the last completed run, kept while a re-run
 * is running.
 */
export interface CredentialCheckReport {
  credential_id: number;
  connector_id: number | null;
  run_status: CredentialCheckRunStatus;
  run_started_at: string | null;
  report: { checked_at: string } | null;
  time_updated: string;
}
