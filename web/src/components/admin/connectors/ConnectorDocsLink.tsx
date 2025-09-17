import { ValidSources } from "@/lib/types";
import { getSourceDocLink } from "@/lib/sources";

export default function ConnectorDocsLink({
  sourceType,
  className,
}: {
  sourceType: ValidSources;
  className?: string;
}) {
  const docsLink = getSourceDocLink(sourceType);

  if (!docsLink) {
    return null;
  }

  const paragraphClass = ["text-sm", className].filter(Boolean).join(" ");

  return (
    <p className={paragraphClass}>
      Check out
      <a
        className="text-blue-600 hover:underline"
        target="_blank"
        rel="noopener"
        href={docsLink}
      >
        {" "}
        our docs{" "}
      </a>
      for more info on configuring this connector.
    </p>
  );
}
