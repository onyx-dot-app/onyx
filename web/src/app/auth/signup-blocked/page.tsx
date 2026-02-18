import AuthFlowContainer from "@/components/auth/AuthFlowContainer";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";

export default function SignupBlockedPage() {
  return (
    <AuthFlowContainer>
      <div className="flex w-full flex-col gap-3">
        <Text as="p" headingH2 text05>
          Account Creation Blocked
        </Text>
        <Text as="p" text03>
          This workspace has allocated all seats to current and invited users.
        </Text>
        <Text as="p" text03>
          Please contact your workspace admin to review seat allocation in Plans
          and Billing before creating another account.
        </Text>
        <div className="pt-2">
          <Button href="/auth/login?autoRedirectToSignup=false">
            Back to Sign In
          </Button>
        </div>
      </div>
    </AuthFlowContainer>
  );
}
