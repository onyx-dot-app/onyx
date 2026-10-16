import { FormikProps } from "formik";
import type { ApiTokenValue } from "@/lib/api-tokens/types";
import { ImageProvider } from "@/views/admin/ImageGenerationPage/constants";
import {
  ImageGenerationConfigView,
  ImageGenerationCredentials,
} from "@/views/admin/ImageGenerationPage/svc";
import type { ModalCreationInterface } from "@opal/components";
import { APIFormFieldState } from "@/refresh-components/form/types";

// Base props for all image generation forms
export interface ImageGenFormBaseProps {
  modal: ModalCreationInterface;
  imageProvider: ImageProvider;
  existingConfig?: ImageGenerationConfigView;
  onSuccess: () => void;
}

// Base type for form values - allows any object structure
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type FormValues = Record<string, any>;

// Props for the generic wrapper component
export interface ImageGenFormWrapperProps<
  T extends FormValues,
> extends ImageGenFormBaseProps {
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
  resetApiState: () => void;
  imageProvider: ImageProvider;
}

// Payload for submitting image generation config
export interface ImageGenSubmitPayload {
  modelName: string;
  imageProviderId: string;
  isDefault?: boolean;

  provider?: string;
  apiKey?: ApiTokenValue;
  apiBase?: string;
  apiVersion?: string;
  deploymentName?: string;
  customConfig?: Record<string, string>;
}
