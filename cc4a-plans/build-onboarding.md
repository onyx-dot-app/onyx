# Build Mode Onboarding Plan

## Overview

Add onboarding modals to Build Mode that collect user info and ensure LLM configuration before users can proceed. All modals are non-closable.

## Modal Logic

| Role | Modals Shown |
|------|--------------|
| Basic | NotAllowed (blocks access) |
| Curator | UserInfo (if name/work area missing) |
| Admin | UserInfo (if missing) → LLM Setup (if no recommended LLMs) |

Cloud users see "Use Onyx's Anthropic Key" option in LLM modal only if they don't have an Anthropic key configured (rare case - they would have deleted the default).

## File Structure

```
web/src/app/build/onboarding/
├── types.ts
├── constants.ts
├── hooks/
│   └── useBuildOnboarding.ts
├── components/
│   ├── UserInfoModal.tsx
│   ├── LlmSetupModal.tsx
│   └── NotAllowedModal.tsx
└── BuildOnboardingProvider.tsx
```

## Implementation

### 1. Types (`types.ts`)

```typescript
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
```

### 2. Constants (`constants.ts`)

```typescript
export const WORK_AREA_OPTIONS = [
  { value: "engineering", label: "Engineering" },
  { value: "product", label: "Product" },
  { value: "executive", label: "Executive" },
  { value: "sales", label: "Sales" },
  { value: "marketing", label: "Marketing" },
];

export const LEVEL_OPTIONS = [
  { value: "ic", label: "IC" },
  { value: "manager", label: "Manager" },
];

export const WORK_AREAS_WITH_LEVEL = ["engineering", "product", "sales"];

export const BUILD_USER_LEVEL_COOKIE_NAME = "build_user_level";
```

### 3. Hook (`useBuildOnboarding.ts`)

```typescript
export function useBuildOnboarding() {
  const { user, isAdmin, isCurator } = useUser();
  const { llmProviders, isLoading } = useLLMProviders();

  const hasUserInfo = !!(user?.personalization?.name && user?.personalization?.role);
  const hasRecommendedLlms = checkHasRecommendedLlms(llmProviders); // e.g. Anthropic configured
  const isBasicUser = !isAdmin && !isCurator;

  const showNotAllowedModal = isBasicUser;

  const flow: BuildOnboardingFlow = {
    showNotAllowedModal,
    showUserInfoModal: !showNotAllowedModal && !hasUserInfo && (isAdmin || isCurator),
    showLlmModal: !showNotAllowedModal && isAdmin && !hasRecommendedLlms,
  };

  return { flow, actions, isLoading };
}
```

### 4. Modal Components

**UserInfoModal.tsx**
- Fields: First name, Last name, Work area (dropdown), Level (dropdown)
- Level only shown for engineering, product, sales
- Saves name/work area via `updateUserPersonalization()`
- Saves level to cookie (`BUILD_USER_LEVEL_COOKIE_NAME`)

**LlmSetupModal.tsx**
- Reuses forms from `@/refresh-components/onboarding/forms/`
- Shows "Use Onyx's Anthropic Key" option when cloud AND no Anthropic key configured

**NotAllowedModal.tsx**
- Message explaining basic users cannot access build mode
- Buttons: "Return to Chat" → `/chat`, "Create a new account" → logs out user via `logout()` from `@/lib/user`, then redirects to `/auth/signup`

### 5. Provider & Integration

**BuildOnboardingProvider.tsx**
```tsx
export function BuildOnboardingProvider({ children }: { children: React.ReactNode }) {
  const { flow, actions, isLoading } = useBuildOnboarding();

  if (isLoading) return <LoadingSpinner />;

  return (
    <>
      <NotAllowedModal open={flow.showNotAllowedModal} />
      <UserInfoModal open={flow.showUserInfoModal} onComplete={actions.completeUserInfo} />
      <LlmSetupModal open={flow.showLlmModal} onComplete={actions.completeLlmSetup} />
      {children}
    </>
  );
}
```

**Modify `web/src/app/build/v1/layout.tsx`**
```tsx
import { BuildOnboardingProvider } from "@/app/build/onboarding/BuildOnboardingProvider";

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <UploadFilesProvider>
      <BuildProvider>
        <BuildOnboardingProvider>
          <div className="flex flex-row w-full h-full">
            <BuildSidebar />
            {children}
          </div>
        </BuildOnboardingProvider>
      </BuildProvider>
    </UploadFilesProvider>
  );
}
```

## Verification

- Basic user → NotAllowedModal
- Curator missing user info → UserInfoModal
- Admin missing user info → UserInfoModal
- Admin with user info, no recommended LLMs → LlmSetupModal
- Level field shows only for engineering/product/sales
