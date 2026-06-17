"use client";

import AuthFlowContainer from "@/refresh-pages/auth/AuthFlowContainer";
import { REGISTRATION_URL } from "@/lib/constants";
import { Button } from "@opal/components";
import { markdown } from "@opal/utils";
import { SvgImport } from "@opal/icons";

export default function Page() {
  return (
    <AuthFlowContainer
      title="Account Not Found"
      description="We couldn't find your account in our records. To access Onyx, you need to either be invited to an existing team or create a new one."
      bottomPrompt={markdown(
        "Have an account with a different email? [Sign in](/auth/login)"
      )}
    >
      <Button
        href={`${REGISTRATION_URL}/register`}
        width="full"
        icon={SvgImport}
      >
        Create New Organization
      </Button>
    </AuthFlowContainer>
  );
}
