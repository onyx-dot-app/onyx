import Button from "@/refresh-components/buttons/Button";
import React, { memo } from "react";
import Text from "@/refresh-components/texts/Text";
import { SvgProps } from "@/icons";
import SvgArrowExchange from "@/icons/arrow-exchange";
import SvgCpu from "@/icons/cpu";
import Truncated from "@/refresh-components/texts/Truncated";
import SvgServer from "@/icons/server";

type LLMProviderProps = {
  title: string;
  description: string;
  icon?: React.FunctionComponent<SvgProps>;
  disabled?: boolean;
};
const LLMProviderInner = ({
  title,
  description,
  icon: Icon,
  disabled,
}: LLMProviderProps) => {
  return (
    <div className="flex justify-between h-full w-full p-spacing-inline rounded-12 border border-border-01 bg-background-neutral-01">
      <div className="flex gap-spacing-inline p-spacing-inline flex-1 min-w-0">
        <div className="h-full p-spacing-inline-mini">
          {Icon ? (
            <Icon className="w-4 h-4" />
          ) : (
            <SvgServer className="w-4 h-4 stroke-text-04" />
          )}
        </div>
        <div className="min-w-0">
          <Text text04 mainUiAction>
            {title}
          </Text>
          <Truncated text03 secondaryBody>
            {description}
          </Truncated>
        </div>
      </div>
      <Button tertiary rightIcon={SvgArrowExchange} disabled={disabled}>
        Connect
      </Button>
    </div>
  );
};

const LLMProvider = memo(LLMProviderInner);
export default LLMProvider;
