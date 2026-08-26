export const forgotPassword = async (
  email: string,
  fallbackErrorMessage: string
): Promise<void> => {
  const response = await fetch(`/api/auth/forgot-password`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ email }),
  });

  if (!response.ok) {
    const error = await response.json();
    const errorMessage = error?.detail || fallbackErrorMessage;
    throw new Error(errorMessage);
  }
};

interface ResetPasswordMessages {
  invalidPassword: string;
  genericError: string;
}

export const resetPassword = async (
  token: string,
  password: string,
  messages: ResetPasswordMessages
): Promise<void> => {
  const response = await fetch(`/api/auth/reset-password`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ token, password }),
  });

  if (!response.ok) {
    const error = await response.json();
    if (error?.detail?.code === "RESET_PASSWORD_INVALID_PASSWORD") {
      throw new Error(error.detail.reason || messages.invalidPassword);
    }
    const errorMessage = error?.detail || messages.genericError;
    throw new Error(errorMessage);
  }
};
