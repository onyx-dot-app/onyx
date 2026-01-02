import { FormikProps } from "formik";
import { ImageProvider } from "../constants";
import { LLMProviderView } from "@/app/admin/configuration/llm/interfaces";
import {
  ImageGenerationConfigView,
  ImageGenerationCredentials,
} from "@/lib/configuration/imageConfigurationService";
import { ModalCreationInterface } from "@/refresh-components/contexts/ModalContext";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { APIFormFieldState } from "@/refresh-components/form/types";

// Base props for all image generation forms
export interface ImageGenFormBaseProps {
  modal: ModalCreationInterface;
  imageProvider: ImageProvider;
  existingProviders: LLMProviderView[];
  existingConfig?: ImageGenerationConfigView;
  onSuccess: () => void;
  setPopup: (popup: PopupSpec | null) => void;
}

// Base type for form values - allows any object structure
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type FormValues = Record<string, any>;

// Props for the generic wrapper component
export interface ImageGenFormWrapperProps<T extends FormValues>
  extends ImageGenFormBaseProps {
  title: string;
  description: string;
  initialValues: T;
  validationSchema: unknown;
  children: (props: ImageGenFormChildProps<T>) => React.ReactNode;
  transformValues?: (values: T) => ImageGenSubmitPayload;
  getInitialValuesFromCredentials?: (
    credentials: ImageGenerationCredentials,
    imageProvider: ImageProvider
  ) => Partial<T>;
}

// Props passed to form field children
export interface ImageGenFormChildProps<T extends FormValues> {
  formikProps: FormikProps<T>;
  apiStatus: APIFormFieldState;
  setApiStatus: (status: APIFormFieldState) => void;
  showApiMessage: boolean;
  setShowApiMessage: (show: boolean) => void;
  errorMessage: string;
  setErrorMessage: (message: string) => void;
  isSubmitting: boolean;
  disabled: boolean;
  isEditMode: boolean;
  isLoadingCredentials: boolean;
  apiKeyOptions: { value: string; label: string }[];
  resetApiState: () => void;
  imageProvider: ImageProvider;
}

// Payload for submitting image generation config
export interface ImageGenSubmitPayload {
  modelName: string;
  imageProviderId: string;
  isDefault?: boolean;

  // Clone mode - reuse credentials from existing LLM provider
  sourceLlmProviderId?: number;

  // New credentials mode
  provider?: string;
  apiKey?: string;
  apiBase?: string;
  apiVersion?: string;
  deploymentName?: string;
}
