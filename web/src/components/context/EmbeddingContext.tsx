import React, {
  createContext,
  useState,
  useContext,
  ReactNode,
  useEffect,
} from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ValidSources } from "@/lib/types";

interface EmbeddingFormContextType {
  formStep: number;
  formValues: Record<string, any>;
  setFormValues: (values: Record<string, any>) => void;
  nextFormStep: (contract?: string) => void;
  prevFormStep: () => void;
  formStepToLast: () => void;
  setFormStep: React.Dispatch<React.SetStateAction<number>>;
  allowAdvanced: boolean;
  setAllowAdvanced: React.Dispatch<React.SetStateAction<boolean>>;
  allowCreate: boolean;
  setAlowCreate: React.Dispatch<React.SetStateAction<boolean>>;
}

const EmbeddingFormContext = createContext<
  EmbeddingFormContextType | undefined
>(undefined);

export const EmbeddingFormProvider: React.FC<{
  children: ReactNode;
}> = ({ children }) => {
  const router = useRouter();
  const searchParams = useSearchParams();
  const pathname = usePathname();

  // Initialize formStep based on the URL parameter
  const initialStep = parseInt(searchParams.get("step") || "0", 10);
  const [formStep, setFormStep] = useState(initialStep);
  const [formValues, setFormValues] = useState<Record<string, any>>({});

  const [allowAdvanced, setAllowAdvanced] = useState(false);
  const [allowCreate, setAlowCreate] = useState(false);

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
    const updatedSearchParams = new URLSearchParams(searchParams.toString());
    updatedSearchParams.set("step", formStep.toString());
    const newUrl = `${pathname}?${updatedSearchParams.toString()}`;
    router.push(newUrl);
  }, [formStep, router, pathname, searchParams]);

  // Update formStep when URL changes
  useEffect(() => {
    const stepFromUrl = parseInt(searchParams.get("step") || "0", 10);
    if (stepFromUrl !== formStep) {
      setFormStep(stepFromUrl);
    }
  }, [searchParams]);

  const contextValue: EmbeddingFormContextType = {
    formStep,
    formValues,
    setFormValues: (values) =>
      setFormValues((prevValues) => ({ ...prevValues, ...values })),
    nextFormStep,
    prevFormStep,
    formStepToLast,
    setFormStep,
    allowAdvanced,
    setAllowAdvanced,
    allowCreate,
    setAlowCreate,
  };

  return (
    <EmbeddingFormContext.Provider value={contextValue}>
      {children}
    </EmbeddingFormContext.Provider>
  );
};

export const useEmbeddingFormContext = () => {
  const context = useContext(EmbeddingFormContext);
  if (context === undefined) {
    throw new Error(
      "useEmbeddingFormContext must be used within a FormProvider"
    );
  }
  return context;
};
