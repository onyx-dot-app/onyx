import React, { memo } from "react";
import Button from "@/refresh-components/buttons/Button";
import SvgExternalLink from "@/icons/external-link";
import Text from "@/refresh-components/texts/Text";
import { FINAL_SETUP_CONFIG } from "../constants";
import { FinalStepItemProps } from "../types";

const FinalStepItemInner = ({
  title,
  description,
  icon: Icon,
  buttonText,
  buttonHref,
}: FinalStepItemProps) => {
  return (
    <div className="flex justify-between h-full w-full p-1 rounded-16 border border-border-01 bg-background-tint-01">
      <div className="flex gap-1 py-2 pr-2 pl-1">
        <div className="h-full p-0.5">
          <Icon className="w-4 h-4 stroke-text-03" />
        </div>
        <div>
          <Text text04 mainUiAction>
            {title}
          </Text>
          <Text text03 secondaryBody>
            {description}
          </Text>
        </div>
      </div>
      <Button tertiary rightIcon={SvgExternalLink} href={buttonHref}>
        {buttonText}
      </Button>
    </div>
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
