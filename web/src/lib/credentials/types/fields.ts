import { TypedFile } from "@/lib/connectors/fileTypes";

export type CredentialFieldValue =
  | string
  | boolean
  | TypedFile
  | null
  | undefined;

export type CredentialFieldValues = Record<string, CredentialFieldValue>;

export interface CredentialFormValues extends CredentialFieldValues {
  name: string;
}

export type CredentialActionType = "create" | "createAndSwap";

/**
 * What a credential form's validation says, already translated. `fieldTitle`
 * names a field by its key; the rest wrap that title in a message.
 */
export interface CredentialValidationMessages {
  fieldTitle: (key: string) => string;
  required: (field: string) => string;
  empty: (field: string) => string;
  invalidEmail: (field: string) => string;
  fileRequired: (field: string) => string;
  authMethodRequired: string;
}
