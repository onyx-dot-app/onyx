import { useFormContext } from "@/components/context/FormContext";
import SvgArrowLeft from "@/icons/arrow-left";
import SvgArrowRight from "@/icons/arrow-right";
import SvgPlusCircle from "@/icons/plus-circle";
import Button from "@/refresh-components/buttons/Button";

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

  return (
    <div className="mt-4 w-full grid grid-cols-3">
      <div>
        {((formStep > 0 && !noCredentials) ||
          (formStep > 1 && !noAdvanced)) && (
          <Button secondary onClick={prevFormStep} leftIcon={SvgArrowLeft}>
            Previous
          </Button>
        )}
      </div>
      <div className="flex justify-center">
        {(formStep > 0 || noCredentials) && (
          <Button
            disabled={!isValid}
            rightIcon={SvgPlusCircle}
            onClick={onSubmit}
          >
            Create Connector
          </Button>
        )}
      </div>
      <div className="flex justify-end">
        {formStep === 0 && (
          <Button
            action
            disabled={!activatedCredential}
            rightIcon={SvgArrowRight}
            onClick={() => nextFormStep()}
          >
            Continue
          </Button>
        )}
        {!noAdvanced && formStep === 1 && (
          <Button
            secondary
            disabled={!isValid}
            rightIcon={SvgArrowRight}
            onClick={() => nextFormStep()}
          >
            Advanced
          </Button>
        )}
      </div>
    </div>
  );
};
export default NavigationRow;
