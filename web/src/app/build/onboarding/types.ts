export interface BuildUserInfo {
  firstName: string;
  lastName: string;
  workArea: string;
  level?: string;
}

export interface BuildOnboardingFlow {
  showNotAllowedModal: boolean;
  showUserInfoModal: boolean;
  showLlmModal: boolean;
}
