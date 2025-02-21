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
            Continue Generation
          </>
        </EmphasizedClickable>
        {showExplanation && (
          <div className="absolute bottom-full left-1/2 transform -translate-x-1/2 mb-2 px-3 py-1 bg-background-800 text-white text-xs rounded-lg opacity-0 group-hover:opacity-100 transition-opacity duration-300 whitespace-nowrap">
            LLM reached its token limit. Click to continue.
          </div>
        )}
      </div>
    </div>
  );
}
