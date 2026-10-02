/** The shape of a source's credential spec. The specs live in `@/lib/credentials/constants`. */
import type en from "@/i18n/messages/en.json";
import type { TypedFile } from "@/lib/connectors/fileTypes";
import type { FileTypeCategory } from "@/lib/connectors/types/fileTypes";

type CredentialMessages = (typeof en)["admin"]["credentials"];

/** A field title in `admin.credentials.displayNames`. May use `{source}`. */
export type CredentialDisplayName = keyof CredentialMessages["displayNames"];

/** A field hint in `admin.credentials.hints`. */
export type CredentialHintKey = keyof CredentialMessages["hints"];

/** An auth-method tab label in `admin.credentials.methods.labels`. */
export type CredentialMethodLabel =
  keyof CredentialMessages["methods"]["labels"];

/** An auth-method description in `admin.credentials.methods.descriptions`. */
export type CredentialMethodDescription =
  keyof CredentialMessages["methods"]["descriptions"];

export interface CredentialHint {
  key: CredentialHintKey;
  values?: Record<string, string>;
}

export interface CredentialFieldOptions {
  /** The backend accepts the credential without this field. */
  optional?: boolean;
  hint?: CredentialHint;
}

interface CredentialFieldBase extends CredentialFieldOptions {
  displayName: CredentialDisplayName;
}

export type CredentialTextKind = "text" | "email" | "url" | "secret";

/** One field of a credential spec. `kind` picks how it renders. */
export type CredentialSpecField =
  | (CredentialFieldBase & { kind: CredentialTextKind })
  | (CredentialFieldBase & { kind: "toggle" })
  | (CredentialFieldBase & { kind: "file"; fileType: FileTypeCategory });

export type CredentialSpecFields = Record<string, CredentialSpecField>;

/** One way to authenticate. It names the spec fields it asks for. */
export interface CredentialSpecMethod<TKey extends string = string> {
  /** The `authentication_method` the backend reads. */
  value: string;
  label: CredentialMethodLabel;
  description?: CredentialMethodDescription;
  fields: readonly TKey[];
  /** Hides the "Auto Sync Permissions" access type for this method. */
  disablePermSync?: boolean;
}

/** A source's credential: its fields and, optionally, its auth methods. */
export interface CredentialSpec {
  /** The name field titles use for `{source}`, like "Microsoft Teams". */
  brandName: string;
  /** Every field, declared once. Keys are what the backend reads. */
  fields: CredentialSpecFields;
  /** Two or more ways to authenticate. The first is the default. */
  methods?: readonly CredentialSpecMethod[];
}

export type MethodsOf<TFields> = readonly CredentialSpecMethod<
  Extract<keyof TFields, string>
>[];

/** A spec that keeps its literal field keys and whether it has methods. */
export interface DefinedCredentialSpec<
  TFields extends CredentialSpecFields,
  TMethods extends MethodsOf<TFields> | undefined,
> {
  brandName: string;
  fields: TFields;
  methods: TMethods;
}

type FieldValueOf<TField> = TField extends { kind: "toggle" }
  ? boolean
  : TField extends { kind: "file" }
    ? TypedFile
    : string;

type RequiredKeys<TFields> = {
  [K in keyof TFields]: TFields[K] extends { optional: true } ? never : K;
}[keyof TFields];

/**
 * The `credential_json` a spec produces. With auth methods, each field is
 * present only under its own method, so every field is optional.
 */
export type CredentialJsonOf<TSpec> = TSpec extends {
  fields: infer TFields;
}
  ? TSpec extends { methods: readonly unknown[] }
    ? { authentication_method?: string } & {
        [K in keyof TFields]?: FieldValueOf<TFields[K]>;
      }
    : { [K in RequiredKeys<TFields>]: FieldValueOf<TFields[K]> } & {
        [K in Exclude<keyof TFields, RequiredKeys<TFields>>]?: FieldValueOf<
          TFields[K]
        > | null;
      }
  : never;
