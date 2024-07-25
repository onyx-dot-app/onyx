import { BooleanFormField } from "./Field";

export default function IsPublicField({
  name = "is_public",
}: {
  name?: string;
}) {
  return (
    <BooleanFormField
      name={name}
      label="Documents are Public?"
      subtext={
        "If set, then documents indexed by this connector will be " +
        "visible to all users. If turned off, then only users who explicitly " +
        "have been given access to the documents (e.g. through a User Group) " +
        "will have access"
      }
    />
  );
}
