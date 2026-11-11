/** A Formik errors tree: a message per field, nested like the form's values. */
export type FormikErrorTree =
  | string
  | undefined
  | FormikErrorTree[]
  | { [field: string]: FormikErrorTree };

/** The first message in a Formik errors tree, depth first in field order, or `null` when it holds none. */
export function firstFormikError(errors: FormikErrorTree): string | null {
  if (errors === undefined) return null;
  if (typeof errors === "string") return errors;
  for (const value of Object.values(errors)) {
    const message = firstFormikError(value);
    if (message !== null) return message;
  }
  return null;
}
