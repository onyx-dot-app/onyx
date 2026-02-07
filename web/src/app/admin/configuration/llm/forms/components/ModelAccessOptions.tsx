"use client";

import * as InputLayouts from "@/layouts/input-layouts";
import InputSelectField from "@/refresh-components/form/InputSelectField";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { useState } from "react";
import { SvgOrganization } from "@opal/icons";
import * as GeneralLayouts from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";
import { Card } from "@/refresh-components/cards";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";

enum ModelAccessOption {
  ALL = "all", // All users and agents
  NAMED = "named", // Only named users and agents
}

export function ModelAccessOptions() {
  const [modelAccessOption, setModelAccessOption] = useState<ModelAccessOption>(
    ModelAccessOption.ALL
  );

  return (
    <>
      <InputLayouts.Horizontal
        title="Model Access"
        description="Who can access this provider."
      >
        <InputSelectField
          name="model_access_options"
          defaultValue={modelAccessOption}
          onValueChange={(value) =>
            setModelAccessOption(value as ModelAccessOption)
          }
        >
          <InputSelect.Trigger />
          <InputSelect.Content>
            <InputSelect.Item value={ModelAccessOption.ALL}>
              All users and agents
            </InputSelect.Item>
            <InputSelect.Item value={ModelAccessOption.NAMED}>
              Named users and agents
            </InputSelect.Item>
          </InputSelect.Content>
        </InputSelectField>
      </InputLayouts.Horizontal>

      {modelAccessOption === ModelAccessOption.NAMED && (
        <NamedModelAccessOptions />
      )}
    </>
  );
}

function NamedModelAccessOptions() {
  return (
    <Card>
      <InputTypeIn
        variant="primary"
        placeholder="Add users, groups, accounts, and agents"
      />
    </Card>
  );
}
