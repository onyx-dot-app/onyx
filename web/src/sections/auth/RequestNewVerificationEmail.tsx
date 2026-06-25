"use client";

import { useState } from "react";
import { Button } from "@opal/components";
import { SvgSimpleLoader } from "@opal/icons";
import { toast } from "@/hooks/useToast";
import { requestEmailVerification } from "@/lib/auth/svc";

interface RequestNewVerificationEmailProps {
  children: string;
  email: string;
}

export default function RequestNewVerificationEmail({
  children,
  email,
}: RequestNewVerificationEmailProps) {
  const [isLoading, setIsLoading] = useState(false);

  const handleClick = async () => {
    setIsLoading(true);
    const response = await requestEmailVerification(email);
    setIsLoading(false);

    if (response.ok) {
      toast.success("A new verification email has been sent!");
    } else {
      const errorDetail = (await response.json()).detail;
      toast.error(`Failed to send a new verification email - ${errorDetail}`);
    }
  };

  return (
    <Button
      prominence="internal"
      icon={isLoading ? SvgSimpleLoader : undefined}
      onClick={handleClick}
      disabled={isLoading}
    >
      {children}
    </Button>
  );
}
