"use client";

import { Fragment } from "react";
import { useFormContext } from "@/components/context/FormContext";
import { credentialTemplates } from "@/lib/connectors/credentials";
import { Text } from "@opal/components";
import { cn } from "@opal/utils";
import StepSidebar from "@/sections/sidebar/StepSidebarWrapper";
import { useUser } from "@/providers/UserProvider";
import { SvgSettings } from "@opal/icons";

// Fixed height of each step row (px). A uniform row height lets the connecting
// rail line up deterministically with every dot regardless of step count.
const STEP_ROW_PX = 36;

type SelectionType = "done" | "current" | "future";

interface SelectionIconProps {
  selected: SelectionType;
}

function SelectionIcon({ selected }: SelectionIconProps) {
  return (
    <div
      className={cn(
        "shrink-0 z-10 rounded-full h-3.5 w-3.5 flex items-center justify-center",
        selected === "future"
          ? "bg-background-tint-04"
          : "bg-action-selection-05"
      )}
    >
      {selected === "current" && (
        <div className="h-1.5 w-1.5 rounded-full bg-background-tint-inverted-00" />
      )}
    </div>
  );
}

export default function Sidebar() {
  const { formStep, setFormStep, connector, allowAdvanced, allowCreate } =
    useFormContext();
  const noCredential = credentialTemplates[connector] == null;

  const { isAdmin } = useUser();
  const buttonName = isAdmin ? "Admin Page" : "Curator Page";

  const settingSteps = [
    ...(!noCredential ? ["Credential"] : []),
    "Connector",
    ...(connector == "file" ? [] : ["Advanced (optional)"]),
  ];

  return (
    <StepSidebar
      buttonName={buttonName}
      buttonIcon={SvgSettings}
      buttonHref="/admin/add-connector"
    >
      <div className="relative mx-2.5 flex flex-col">
        {settingSteps.map((step, index) => {
          const allowed =
            (step == "Connector" && allowCreate) ||
            (step == "Advanced (optional)" && allowAdvanced) ||
            index <= formStep;

          return (
            <Fragment key={index}>
              {index !== 0 && (
                <div
                  className={cn(
                    "absolute left-1.5 w-0.5",
                    index <= formStep
                      ? "bg-action-selection-05"
                      : "bg-background-tint-04"
                  )}
                  style={{
                    top: (index - 1) * STEP_ROW_PX + STEP_ROW_PX / 2,
                    height: STEP_ROW_PX,
                  }}
                />
              )}
              <div
                className={cn(
                  "flex items-center gap-4",
                  allowed ? "cursor-pointer" : "cursor-not-allowed"
                )}
                style={{ height: STEP_ROW_PX }}
                onClick={() => {
                  if (allowed) {
                    setFormStep(index - (noCredential ? 1 : 0));
                  }
                }}
              >
                <SelectionIcon
                  selected={
                    formStep === index
                      ? "current"
                      : formStep < index
                        ? "future"
                        : "done"
                  }
                />
                <Text
                  as="p"
                  font="main-ui-body"
                  color={index <= formStep ? "text-04" : "text-02"}
                >
                  {step}
                </Text>
              </div>
            </Fragment>
          );
        })}
      </div>
    </StepSidebar>
  );
}
