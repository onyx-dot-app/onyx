import { TypedFile } from "@/lib/connectors/fileTypes";

type CredentialFieldValue = string | boolean | TypedFile | null | undefined;

export type CredentialFieldValues = Record<string, CredentialFieldValue>;

export interface CredentialFormValues extends CredentialFieldValues {
  name: string;
}

export type CredentialActionType = "create" | "createAndSwap";
