"use client";

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
        {settingSteps.length > 1 && (
          <div
            className="absolute left-[6px] w-0.5 bg-background-tint-04"
            style={{
              top: STEP_ROW_PX / 2,
              height: (settingSteps.length - 1) * STEP_ROW_PX,
            }}
          />
        )}
        {settingSteps.map((step, index) => {
          const allowed =
            (step == "Connector" && allowCreate) ||
            (step == "Advanced (optional)" && allowAdvanced) ||
            index <= formStep;

          return (
            <div
              key={index}
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
              <div
                className={cn(
                  "shrink-0 z-10 rounded-full h-3.5 w-3.5 flex items-center justify-center",
                  allowed ? "bg-action-selection-05" : "bg-background-tint-04"
                )}
              >
                {formStep === index && (
                  <div className="h-2 w-2 rounded-full bg-background-neutral-00" />
                )}
              </div>
              <Text
                as="p"
                font="main-ui-body"
                color={index <= formStep ? "text-04" : "text-02"}
              >
                {step}
              </Text>
            </div>
          );
        })}
      </div>
    </StepSidebar>
  );
}
