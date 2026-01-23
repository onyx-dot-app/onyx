# Build Onboarding Modification

## Change Summary

Basic users can now access Build Mode and complete the user info modal. They are only blocked when attempting to connect a connector.

## Updated Modal Logic

| Role | User Info Modal | Connector Block Modal |
|------|-----------------|----------------------|
| Basic | Yes (if name/work area missing) | Yes (when connecting connector) |
| Curator | Yes (if name/work area missing) | No |
| Admin | Yes (if missing) → LLM Setup (if no recommended LLMs) | No |

## Changes Required

### 1. Rename NotAllowedModal → ConnectorBlockedModal

Update `web/src/app/build/onboarding/components/NotAllowedModal.tsx`:
- Rename to `ConnectorBlockedModal.tsx`
- Change title to reflect connector-specific blocking
- Replace "Return to Chat" with "Cancel" button (closes modal)
- Keep "Create a new account" button (logs out → signup)

### 2. Update useBuildOnboarding Hook

In `web/src/app/build/onboarding/hooks/useBuildOnboarding.ts`:
- Remove `showNotAllowedModal` from initial flow
- Add basic users to `showUserInfoModal` condition
- Export a new `showConnectorBlockedModal` function/state that can be triggered externally

```typescript
// Before
const showNotAllowedModal = isBasicUser;
const flow = {
  showNotAllowedModal,
  showUserInfoModal: !showNotAllowedModal && !hasUserInfo && (isAdmin || isCurator),
  showLlmModal: !showNotAllowedModal && isAdmin && !hasRecommendedLlms,
};

// After
const flow = {
  showUserInfoModal: !hasUserInfo, // All roles see this if missing
  showLlmModal: isAdmin && !hasRecommendedLlms,
};

// New: expose function to show connector blocked modal
const [showConnectorBlocked, setShowConnectorBlocked] = useState(false);
```

### 3. Update BuildOnboardingProvider

In `web/src/app/build/onboarding/BuildOnboardingProvider.tsx`:
- Remove automatic NotAllowedModal rendering
- Export context with `showConnectorBlockedModal` function
- Render ConnectorBlockedModal controlled by state

```tsx
const BuildOnboardingContext = createContext<{
  showConnectorBlockedModal: () => void;
} | null>(null);

export function useBuildOnboardingContext() {
  return useContext(BuildOnboardingContext);
}
```

### 4. Integrate with Connector Flow

Where connector connection is triggered (likely in configure step):
- Check if user is basic (`!isAdmin && !isCurator`)
- If basic, call `showConnectorBlockedModal()` instead of proceeding
- Modal appears with Cancel/Create new account options

## File Changes

| File | Action |
|------|--------|
| `NotAllowedModal.tsx` | Rename to `ConnectorBlockedModal.tsx`, update copy and buttons |
| `useBuildOnboarding.ts` | Update flow logic, add connector blocked state |
| `BuildOnboardingProvider.tsx` | Add context, update modal rendering |
| `types.ts` | Update `BuildOnboardingFlow` interface |
| Connector trigger location | Add check for basic user and call modal |

## ConnectorBlockedModal UI

- **Title**: "Admin Access Required"
- **Description**: "Connecting data sources requires admin privileges. Create a new account or contact your administrator for access."
- **Buttons**:
  - Cancel (secondary) → closes modal
  - Create a new account (primary) → logout → `/auth/signup`

---

## Build Mode Intro Notification

### Current Behavior
The "dramatic build mode intro" animation is controlled by a notification created in the backend. Currently, it only shows for admin users.

**Backend file**: `backend/onyx/server/features/build/utils.py`

```python
# Line 315-317 - Current logic
if user.role != UserRole.ADMIN:
    return
```

### Required Change
Since basic users can now access Build Mode, the intro notification should be shown to all users (not just admins).

**Updated logic**:
```python
# Remove the admin-only check, or update to include all roles
# Option 1: Remove check entirely (show to everyone)
# Option 2: Show to admin, curator, and basic users explicitly
```

### File Changes

| File | Action |
|------|--------|
| `backend/onyx/server/features/build/utils.py` | Remove or update `user.role != UserRole.ADMIN` check in `ensure_build_mode_intro_notification()` |

### Frontend Reference
The intro animation is triggered in `web/src/sections/sidebar/AppSidebar.tsx`:
- Looks for `build_mode` feature announcement notification
- Shows `IntroContent` component when notification exists
- Dismisses notification after user completes intro
