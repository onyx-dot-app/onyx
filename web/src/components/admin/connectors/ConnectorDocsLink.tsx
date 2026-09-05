import { ValidSources } from "@/lib/types";
import { getSourceDocLink } from "@/lib/sources";
import { useTranslations } from "next-intl";

export default function ConnectorDocsLink({
  sourceType,
  className,
}: {
  sourceType: ValidSources;
  className?: string;
}) {
  const t = useTranslations("admin.connector.docsLink");
  const docsLink = getSourceDocLink(sourceType);

  if (!docsLink) {
    return null;
  }

  const paragraphClass = ["text-sm", className].filter(Boolean).join(" ");

  return (
    <p className={paragraphClass}>
      {t.rich("checkOutDocs.text", {
        link: (chunks) => (
          <a
            className="text-blue-600 hover:underline"
            target="_blank"
            rel="noopener"
            href={docsLink}
          >
            {chunks}
          </a>
        ),
      })}
    </p>
  );
}
