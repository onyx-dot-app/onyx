import i18n from "@/i18n/init";
import k from "./../../../i18n/keys";
import { EmphasizedClickable } from "@/components/BasicClickable";
import { useEffect, useState } from "react";
import { FiPlayCircle } from "react-icons/fi";

export function ContinueGenerating({
  handleContinueGenerating,
}: {
  handleContinueGenerating: () => void;
}) {
  const [showExplanation, setShowExplanation] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => {
      setShowExplanation(true);
    }, 1000);

    return () => clearTimeout(timer);
  }, []);

  return (
    <div className="flex justify-center w-full">
      <div className="relative group">
        <EmphasizedClickable onClick={handleContinueGenerating}>
          <>
            <FiPlayCircle className="mr-2" />
            {i18n.t(k.CONTINUE_GENERATION)}
          </>
        </EmphasizedClickable>
        {showExplanation && (
          <div className="absolute bottom-full left-1/2 transform -translate-x-1/2 mb-2 px-3 py-1 bg-background-800 text-white text-xs rounded-lg opacity-0 group-hover:opacity-100 transition-opacity duration-300 whitespace-nowrap">
            {i18n.t(k.LLM_REACHED_ITS_TOKEN_LIMIT_C)}
          </div>
        )}
      </div>
    </div>
  );
}
