import { Section } from "@/layouts/general-layouts";
import { IllustrationContent } from "@opal/layouts";
import SvgNotFound from "@opal/illustrations/not-found";
import SvgNoAccess from "@opal/illustrations/no-access";
import SvgDisconnected from "@opal/illustrations/disconnected";
import { Button } from "@opal/components";
import type { IconFunctionComponent } from "@opal/types";

type ErrorType = "not_found" | "access_denied" | "fetch_error";

const errorConfig: Record<
  ErrorType,
  {
    illustration: IconFunctionComponent;
    title: string;
    description: string;
  }
> = {
  not_found: {
    illustration: SvgNotFound,
    title: "Not found",
    description: "This resource doesn't exist or has been deleted.",
  },
  access_denied: {
    illustration: SvgNoAccess,
    title: "Access denied",
    description: "You don't have permission to view this resource.",
  },
  fetch_error: {
    illustration: SvgDisconnected,
    title: "Something went wrong",
    description: "We couldn't load this resource. Please try again later.",
  },
};

interface ResourceErrorPageProps {
  errorType: ErrorType;
  title?: string;
  description?: string;
  backHref: string;
  backLabel?: string;
}

function ResourceErrorPage({
  errorType,
  title,
  description,
  backHref,
  backLabel = "Go back",
}: ResourceErrorPageProps) {
  const config = errorConfig[errorType];

  return (
    <Section flexDirection="column" alignItems="center" gap={1}>
      <IllustrationContent
        illustration={config.illustration}
        title={title ?? config.title}
        description={description ?? config.description}
      />
      <Button href={backHref} prominence="secondary">
        {backLabel}
      </Button>
    </Section>
  );
}

export default ResourceErrorPage;
