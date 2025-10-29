import React, { memo, useState } from "react";
import Text from "@/refresh-components/texts/Text";
import SvgUser from "@/icons/user";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { OnboardingState, OnboardingActions } from "../types";

type NameStepProps = {
  state: OnboardingState;
  actions: OnboardingActions;
};

const NameStepInner = ({
  state: onboardingState,
  actions: onboardingActions,
}: NameStepProps) => {
  const [name, setName] = useState("");
  return (
    <div className="flex items-center justify-between w-full max-w-[800px] p-3 bg-background-tint-00 rounded-16 border border-border-01">
      <div className="flex items-center gap-1 h-full">
        <div className="h-full p-0.5">
          <SvgUser className="w-4 h-4 stroke-text-03" />
        </div>
        <div>
          <Text text04 mainUiAction>
            What should Onyx call you?
          </Text>
          <Text text03 secondaryBody>
            We will display this name in the app.
          </Text>
        </div>
      </div>
      <InputTypeIn
        placeholder="Your name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        className="w-[26%] min-w-40"
      />
    </div>
  );
};

const NameStep = memo(NameStepInner);
export default NameStep;
