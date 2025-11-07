import React, {
  createContext,
  useState,
  useContext,
  ReactNode,
  useEffect,
} from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ValidSources } from "@/lib/types";

interface FormContextType {
  formStep: number;
  formValues: Record<string, any>;
  setFormValues: (values: Record<string, any>) => void;
  nextFormStep: (contract?: string) => void;
  prevFormStep: () => void;
  formStepToLast: () => void;
  connector: ValidSources;
  setFormStep: React.Dispatch<React.SetStateAction<number>>;
  allowAdvanced: boolean;
  setAllowAdvanced: React.Dispatch<React.SetStateAction<boolean>>;
  allowCreate: boolean;
  setAllowCreate: React.Dispatch<React.SetStateAction<boolean>>;
}

const FormContext = createContext<FormContextType | undefined>(undefined);

// TODO: deprecate this
export const FormProvider: React.FC<{
  children: ReactNode;
  connector: ValidSources;
}> = ({ children, connector }) => {
  const router = useRouter();
  const searchParams = useSearchParams();
  const pathname = usePathname();

  // Initialize formStep based on the URL parameter
  const formStepFromUrlParams = parseInt(searchParams?.get("step") || "0", 10);
  const [formStep, setFormStep] = useState(formStepFromUrlParams);
  const [formValues, setFormValues] = useState<Record<string, any>>({});

  const [allowAdvanced, setAllowAdvanced] = useState(false);
  const [allowCreate, setAllowCreate] = useState(false);

  const nextFormStep = (values = "") => {
    setFormStep((prevStep) => prevStep + 1);
    setFormValues((prevValues) => ({ ...prevValues, values }));
  };

  const prevFormStep = () => {
    setFormStep((currentStep) => Math.max(currentStep - 1, 0));
  };

  const formStepToLast = () => {
    setFormStep(2);
  };

  useEffect(() => {
    // Update URL when formStep changes
    const updatedSearchParams = new URLSearchParams(
      searchParams?.toString() || ""
    );
    updatedSearchParams.set("step", formStep.toString());
    const newUrl = `${pathname}?${updatedSearchParams.toString()}`;

    if (!formStepFromUrlParams) {
      router.replace(newUrl);
    } else if (newUrl !== pathname) {
      router.push(newUrl);
    }
  }, [formStep, router, pathname, formStepFromUrlParams]);

  useEffect(() => {
    if (formStepFromUrlParams !== formStep) {
      setFormStep(formStepFromUrlParams);
    }
  }, [formStepFromUrlParams]);

  const contextValue: FormContextType = {
    formStep,
    formValues,
    setFormValues: (values) =>
      setFormValues((prevValues) => ({ ...prevValues, ...values })),
    nextFormStep,
    prevFormStep,
    formStepToLast,
    setFormStep,
    connector,
    allowAdvanced,
    setAllowAdvanced,
    allowCreate,
    setAllowCreate,
  };

  return (
    <FormContext.Provider value={contextValue}>{children}</FormContext.Provider>
  );
};

export const useFormContext = () => {
  const context = useContext(FormContext);
  if (context === undefined) {
    throw new Error("useFormContext must be used within a FormProvider");
  }
  return context;
};
