import { memo } from "react";
import Link from "next/link";
import type { Route } from "next";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import { FINAL_SETUP_CONFIG } from "../constants";
import { FinalStepItemProps } from "../types";
import { SvgExternalLink } from "@opal/icons";

const FinalStepItemInner = ({
  title,
  description,
  icon: Icon,
  buttonText,
  buttonHref,
}: FinalStepItemProps) => {
  const isExternalLink = buttonHref.startsWith("http");
  const linkProps = isExternalLink
    ? { target: "_blank", rel: "noopener noreferrer" }
    : {};

  const content = (
    <>
      <div className="flex gap-1 py-2 pr-2 pl-1">
        <div className="h-full p-0.5">
          <Icon className="w-4 h-4 stroke-text-03" />
        </div>
        <div>
          <Text as="p" text04 mainUiAction>
            {title}
          </Text>
          <Text as="p" text03 secondaryBody>
            {description}
          </Text>
        </div>
      </div>
      <Button tertiary rightIcon={SvgExternalLink}>
        {buttonText}
      </Button>
    </>
  );

  const className =
    "flex justify-between h-full w-full p-1 rounded-16 border border-border-01 bg-background-tint-01 hover:bg-background-tint-02 transition-colors group";

  if (isExternalLink) {
    return (
      <a href={buttonHref} className={className} {...linkProps}>
        {content}
      </a>
    );
  }

  return (
    <Link href={buttonHref as Route} className={className} {...linkProps}>
      {content}
    </Link>
  );
};

const FinalStepItem = memo(FinalStepItemInner);

const FinalStep = () => {
  return (
    <div className="flex flex-col gap-2 w-full">
      {FINAL_SETUP_CONFIG.map((item) => (
        <FinalStepItem key={item.title} {...item} />
      ))}
    </div>
  );
};

export default FinalStep;
