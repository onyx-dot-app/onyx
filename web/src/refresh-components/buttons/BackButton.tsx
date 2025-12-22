"use client";

import Button from "@/refresh-components/buttons/Button";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import { SvgArrowLeft } from "@opal/icons";

export interface BackButtonProps {
  behaviorOverride?: () => void;
  routerOverride?: string;
}

export default function BackButton({
  behaviorOverride,
  routerOverride,
}: BackButtonProps) {
  const router = useRouter();

  return (
    <Button
      leftIcon={SvgArrowLeft}
      tertiary
      onClick={() => {
        if (behaviorOverride) {
          behaviorOverride();
        } else if (routerOverride) {
          router.push(routerOverride as Route);
        } else {
          router.back();
        }
      }}
    >
      Back
    </Button>
  );
}
