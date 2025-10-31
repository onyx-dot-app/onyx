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
}: FinalStepItemProps) => {
  return (
    <div className="flex justify-between h-full w-full p-spacing-inline rounded-16 border border-border-01 bg-background-tint-01">
      <div className="flex gap-spacing-inline p-spacing-interline">
        <div className="h-full p-spacing-inline-mini">
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
      <Button tertiary rightIcon={SvgExternalLink}>
        {buttonText}
      </Button>
    </div>
  );
};

const FinalStepItem = memo(FinalStepItemInner);

const FinalStep = () => {
  return (
    <div className="flex flex-col gap-spacing-interline w-full">
      {FINAL_SETUP_CONFIG.map((item) => (
        <FinalStepItem key={item.title} {...item} />
      ))}
    </div>
  );
};

export default FinalStep;
