import type { SWRResponse } from "swr";
import type { CredentialCreationMethod } from "@/lib/credentials/credentialCreation";
import type { CredentialFieldValues } from "@/lib/credentials/types/fields";
import type { ValidSources } from "@/lib/connectors/types/source";
import type { TypedFile } from "@/lib/connectors/fileTypes";

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
export interface AuthMethodOption<
  TFields,
  TAuthMethod extends string = string,
> {
  value: TAuthMethod;
  label: string;
  fields: TFields;
  description?: string;
  // UI-only: if true, hide/disable the "Auto Sync Permissions" access type when this auth is used
  disablePermSync?: boolean;
}
export interface CredentialTemplateWithAuth<
  TFields,
  TAuthMethod extends string = string,
> {
  authentication_method?: TAuthMethod;
  authMethods?: AuthMethodOption<Partial<TFields>, TAuthMethod>[];
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
  time_created: string;
  time_updated: string;
}

/**
 * A credential as the UI handles it, with no constraint on the shape of its
 * secret. Credential forms are built from per-source templates, so the call
 * sites that only list, pick or delete a credential never know that shape.
 */
export type AnyCredential = Credential<Record<string, unknown>>;

/**
 * What `useSourceCredentials` returns: every credential the current admin
 * can see for one source.
 *
 * `data` is undefined until the first response lands. The endpoint filters
 * by permission, so each entry is the caller's to edit and delete.
 */
export type SourceCredentialsResult = SWRResponse<AnyCredential[], Error>;

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
  credentials: AnyCredential[] | undefined;
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
  /** The source's credential field template, absent for a source with none. */
  template: CredentialFieldValues | undefined;
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
