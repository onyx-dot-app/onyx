import { useEmbeddingFormContext } from "@/components/context/EmbeddingContext";
import Text from "@/refresh-components/texts/Text";
import StepSidebar from "@/sections/sidebar/StepSidebarWrapper";
import SvgSettings from "@/icons/settings";

export default function EmbeddingSidebar() {
  const { formStep, setFormStep } = useEmbeddingFormContext();

  const settingSteps = ["Embedding Model", "Reranking Model", "Advanced"];

  return (
    <StepSidebar
      buttonName="Search Settings"
      buttonIcon={SvgSettings}
      buttonHref="/admin/configuration/search"
    >
      <div className="relative">
        <div className="absolute h-[85%] left-[6px] top-[8px] bottom-0 w-0.5 bg-background-tint-04"></div>
        {settingSteps.map((step, index) => {
          const allowed = true; // All steps are always allowed for embedding configuration

          return (
            <div
              key={index}
              className={`flex items-center mb-6 relative ${
                !allowed ? "cursor-not-allowed" : "cursor-pointer"
              }`}
              onClick={() => {
                if (allowed) {
                  setFormStep(index);
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
