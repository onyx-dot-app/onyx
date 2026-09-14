import React from "react";

import {
  createCredential,
  createCredentialWithPrivateKey,
} from "@/lib/credential";
import {
  CredentialBase,
  Credential,
  CredentialWithPrivateKey,
} from "@/lib/connectors/credentials";

const PRIVATE_KEY_FIELD_KEY = "private_key";

// Localized message builders. Callers inside components pass translated
// strings. The English defaults cover call sites that pass no messages.
interface SubmitCredentialMessages {
  success: () => string;
  error: (detail: string) => string;
}

export async function submitCredential<T>(
  credential: CredentialBase<T> | CredentialWithPrivateKey<T>,
  messages?: SubmitCredentialMessages
): Promise<{
  credential?: Credential<any>;
  message: string;
  isSuccess: boolean;
}> {
  const buildSuccess = messages?.success ?? (() => "Success!");
  const buildError =
    messages?.error ?? ((detail: string) => `Error: ${detail}`);
  let _isSuccess = false;
  try {
    let response: Response;
    if (PRIVATE_KEY_FIELD_KEY in credential && credential.private_key) {
      response = await createCredentialWithPrivateKey(
        credential as CredentialWithPrivateKey<T>
      );
    } else {
      response = await createCredential(credential as CredentialBase<T>);
    }
    if (response.ok) {
      const parsed_response = await response.json();
      const credential = parsed_response.credential;
      _isSuccess = true;
      return { credential, message: buildSuccess(), isSuccess: true };
    } else {
      const errorData = await response.json();
      return {
        message: buildError(String(errorData.detail)),
        isSuccess: false,
      };
    }
  } catch (error) {
    return { message: buildError(String(error)), isSuccess: false };
  }
}
