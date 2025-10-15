import { useFormContext } from "@/components/context/FormContext";
import { credentialTemplates } from "@/lib/connectors/credentials";
import Text from "@/refresh-components/texts/Text";
import StepSidebar from "@/sections/sidebar/StepSidebarWrapper";
import SvgSettings from "@/icons/settings";
import { useUser } from "@/components/user/UserProvider";

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
      <div className="relative">
        {connector != "file" && (
          <div className="absolute h-[85%] left-[6px] top-[8px] bottom-0 w-0.5 bg-background-tint-04"></div>
        )}
        {settingSteps.map((step, index) => {
          const allowed =
            (step == "Connector" && allowCreate) ||
            (step == "Advanced (optional)" && allowAdvanced) ||
            index <= formStep;

          return (
            <div
              key={index}
              className={`flex items-center mb-6 relative ${
                !allowed ? "cursor-not-allowed" : "cursor-pointer"
              }`}
              onClick={() => {
                if (allowed) {
                  setFormStep(index - (noCredential ? 1 : 0));
                }
              }}
            >
              <div className="flex-shrink-0 mr-4 z-10">
                <div
                  className={`rounded-full h-3.5 w-3.5 flex items-center justify-center ${
                    allowed ? "bg-blue-500" : "bg-background-tint-04"
                  }`}
                >
                  {formStep === index && (
                    <div className="h-2 w-2 rounded-full bg-white"></div>
                  )}
                </div>
              </div>
              <Text text04={index <= formStep} text02={index > formStep}>
                {step}
              </Text>
            </div>
          );
        })}
      </div>
    </StepSidebar>
  );
}
