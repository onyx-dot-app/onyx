import { useFormContext } from "@/components/context/FormContext";
import { ArrowLeft, ArrowRight } from "@phosphor-icons/react";
import { FiPlus } from "react-icons/fi";

const NavigationRow = ({
  noAdvanced,
  noCredentials,
  activatedCredential,
  onSubmit,
  isValid,
}: {
  isValid: boolean;
  onSubmit: () => void;
  noAdvanced: boolean;
  noCredentials: boolean;
  activatedCredential: boolean;
}) => {
  const { formStep, prevFormStep, nextFormStep } = useFormContext();
  const SquareNavigationButton = ({
    onClick,
    disabled,
    className,
    children,
  }: {
    onClick: () => void;
    disabled?: boolean;
    className: string;
    children: React.ReactNode;
  }) => (
    <button
      className={`flex items-center gap-1 text-sm rounded-sm ${className}`}
      onMouseDown={() => !disabled && onClick()}
      disabled={disabled}
    >
      {children}
    </button>
  );

  return (
    <div className="mt-4 w-full grid grid-cols-3">
      <div>
        {((formStep > 0 && !noCredentials) ||
          (formStep > 1 && !noAdvanced)) && (
          <SquareNavigationButton
            className="border border-text-400 mr-auto p-2.5"
            onClick={prevFormStep}
          >
            <ArrowLeft />
            Previous
          </SquareNavigationButton>
        )}
      </div>

      <div className="flex justify-center">
        {(formStep > 0 || noCredentials) && (
          <SquareNavigationButton
            className="bg-accent text-white py-2.5 px-3.5 disabled:opacity-50"
            disabled={!isValid}
            onClick={onSubmit}
          >
            Create Connector
            <FiPlus className="h-4 w-4" />
          </SquareNavigationButton>
        )}
      </div>

      <div className="flex justify-end">
        {formStep === 0 && (
          <SquareNavigationButton
            className="bg-blue-400 text-white py-2.5 px-3.5 disabled:bg-blue-200"
            disabled={!activatedCredential}
            onClick={nextFormStep}
          >
            Continue
            <ArrowRight />
          </SquareNavigationButton>
        )}
        {!noAdvanced && formStep === 1 && (
          <SquareNavigationButton
            className="text-text-600 disabled:text-text-400 py-2.5 px-3.5"
            disabled={!isValid}
            onClick={nextFormStep}
          >
            Advanced
            <ArrowRight />
          </SquareNavigationButton>
        )}
      </div>
    </div>
  );
};
export default NavigationRow;
