import { useFormContext } from "@/components/context/FormContext";
import { Button } from "@opal/components";
import { SvgArrowLeft, SvgArrowRight, SvgPlusCircle } from "@opal/icons";

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
          <Button prominence="secondary" onClick={prevFormStep} icon={SvgArrowLeft}>
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
            variant="action"
            disabled={!activatedCredential}
            rightIcon={SvgArrowRight}
            onClick={() => nextFormStep()}
          >
            Continue
          </Button>
        )}
        {!noAdvanced && formStep === 1 && (
          <Button
            prominence="secondary"
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
