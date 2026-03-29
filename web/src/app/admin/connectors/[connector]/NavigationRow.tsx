import { useFormContext } from "@/components/context/FormContext";
import { Button } from "@opal/components";
import { Disabled } from "@opal/core";
import { SvgArrowLeft, SvgArrowRight, SvgPlusCircle } from "@opal/icons";

const NavigationRow = ({
  noAdvanced,
  noCredentials,
  activatedCredential,
  onSubmit,
  isValid,
  connector,
}: {
  isValid: boolean;
  onSubmit: () => void;
  noAdvanced: boolean;
  noCredentials: boolean;
  activatedCredential: boolean;
  connector?: string;
}) => {
  const { formStep, prevFormStep, nextFormStep } = useFormContext();

  return (
    <div className="mt-4 w-full grid grid-cols-3">
      <div>
        {((formStep > 0 && !noCredentials) ||
          (formStep > 1 && !noAdvanced)) && (
          <Button
            prominence="secondary"
            onClick={prevFormStep}
            icon={SvgArrowLeft}
          >
            Previous
          </Button>
        )}
      </div>
      <div className="flex justify-center">
        {(formStep > 0 || noCredentials) && (
          <Disabled disabled={!isValid}>
            <Button rightIcon={SvgPlusCircle} onClick={onSubmit}>
              {connector === "file" ? "Create Folder" : "Create Connector"}
            </Button>
          </Disabled>
        )}
      </div>
      <div className="flex justify-end">
        {formStep === 0 && (
          <Disabled disabled={!activatedCredential}>
            <Button
              variant="action"
              rightIcon={SvgArrowRight}
              onClick={() => nextFormStep()}
            >
              Continue
            </Button>
          </Disabled>
        )}
        {!noAdvanced && formStep === 1 && (
          <Disabled disabled={!isValid}>
            <Button
              prominence="secondary"
              rightIcon={SvgArrowRight}
              onClick={() => nextFormStep()}
            >
              Advanced
            </Button>
          </Disabled>
        )}
      </div>
    </div>
  );
};
export default NavigationRow;
