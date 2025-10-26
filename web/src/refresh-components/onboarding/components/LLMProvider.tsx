import Button from "@/refresh-components/buttons/Button";
import React, { memo } from "react";
import Text from "@/refresh-components/texts/Text";
import { SvgProps } from "@/icons";
import SvgArrowExchange from "@/icons/arrow-exchange";

type LLMProviderProps = {
  title: string;
  description: string;
  icon: React.FunctionComponent<SvgProps>;
};
const LLMProviderInner = ({
  title,
  description,
  icon: Icon,
}: LLMProviderProps) => {
  return (
    <div className="flex justify-between h-full w-full p-spacing-inline rounded-12 border border-border-01 bg-background-neutral-01">
      <div className="flex gap-spacing-inline p-spacing-inline">
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
      <Button tertiary rightIcon={SvgArrowExchange}>
        Connect
      </Button>
    </div>
  );
};

const LLMProvider = memo(LLMProviderInner);
export default LLMProvider;
