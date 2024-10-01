"use client";

import { WelcomeTopBar } from "@/components/TopBar";
import { Button } from "@/components/ui/button";
import {
  InputOTP,
  InputOTPGroup,
  InputOTPSeparator,
  InputOTPSlot,
} from "@/components/ui/input-otp";
import { ShieldEllipsis } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useToast } from "@/hooks/use-toast";
import { Spinner } from "@/components/Spinner";
import { HealthCheckBanner } from "@/components/health/healthcheck";

const Page = () => {
  const { toast } = useToast();
  const [value, setValue] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const router = useRouter();
  const searchParams = useSearchParams();
  const user_email = searchParams.get("email");

  const handleBackButton = async () => {
    const response = await fetch("/auth/logout", {
      method: "POST",
      credentials: "include",
    });
    router.push("/auth/login");
    return response;
  };

  useEffect(() => {
    const handleUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      handleBackButton();
    };

    window.addEventListener("beforeunload", handleUnload);

    return () => {
      window.removeEventListener("beforeunload", handleUnload);
    };
  }, []);

  const handleContinue = async () => {
    try {
      const response = await fetch("/api/users/verify-otp", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ otp_code: value }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "Error verifying OTP");
      }

      const data = await response.json();
      console.log(data.message);

      router.push("/chat");
    } catch (error) {
      toast({
        title: "Failed to authenticate. Invalid OTP code",
        description: `The code entered by the user does not match the code generated by the system or has expired`,
        variant: "destructive",
      });
      console.error("Error:", error);
    }
  };

  const handleResendOTP = async () => {
    setIsLoading(true);
    const response = await fetch("/api/users/generate-otp", {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      credentials: "include",
    });
    if (!response.ok) {
      toast({
        title: "Failed to Resend OTP Code",
        description: `We encountered an issue while trying to resend the OTP code. Please try again or contact support if the problem persists. ${response.statusText}`,
        variant: "destructive",
      });
    }
    toast({
      title: "OTP Code Resent Successfully",
      description:
        "A new OTP code has been sent to your registered email/phone. Please check your inbox or messages to retrieve it.",
      variant: "success",
    });
    setIsLoading(false);
  };

  return (
    <main className="h-full">
      {isLoading && <Spinner />}
      <HealthCheckBanner />
      <WelcomeTopBar />
      <div className="w-full h-full flex items-center justify-center px-6">
        <div className="md:w-[500px] w-full">
          <div className="flex items-center justify-center">
            <div className="bg-primary p-3 rounded-md">
              <ShieldEllipsis size={60} stroke="white" />
            </div>
          </div>

          <div className="pt-8">
            <h1 className="text-2xl xl:text-3xl font-bold text-center text-dark-900">
              Setup Two-Factor Authentication
            </h1>
            <p className="text-center pt-2 text-sm text-subtle">
              Please check your email a 6 digit code has been sent to your
              registered email{" "}
              <span className="font-semibold text-default">“{user_email}”</span>
            </p>
          </div>

          <div className="pt-8 flex items-center flex-col gap-8 justify-center">
            <InputOTP
              maxLength={6}
              value={value}
              onChange={(value) => setValue(value)}
            >
              <InputOTPGroup>
                <InputOTPSlot
                  index={0}
                  className="w-10 h-10 sm:w-14 sm:h-14 md:h-16 md:w-16 text-3xl font-bold"
                />
                <InputOTPSlot
                  index={1}
                  className="w-10 h-10 sm:w-14 sm:h-14 md:h-16 md:w-16 text-3xl font-bold"
                />
                <InputOTPSlot
                  index={2}
                  className="w-10 h-10 sm:w-14 sm:h-14 md:h-16 md:w-16 text-3xl font-bold"
                />
              </InputOTPGroup>
              <InputOTPSeparator />
              <InputOTPGroup>
                <InputOTPSlot
                  index={3}
                  className="w-10 h-10 sm:w-14 sm:h-14 md:h-16 md:w-16 text-3xl font-bold"
                />
                <InputOTPSlot
                  index={4}
                  className="w-10 h-10 sm:w-14 sm:h-14 md:h-16 md:w-16 text-3xl font-bold"
                />
                <InputOTPSlot
                  index={5}
                  className="w-10 h-10 sm:w-14 sm:h-14 md:h-16 md:w-16 text-3xl font-bold"
                />
              </InputOTPGroup>
            </InputOTP>

            <Button className="w-full" onClick={handleContinue}>
              Continue
            </Button>

            <p className="text-center text-sm">
              Didn&apos;t receive a code?{" "}
              <Link
                href=""
                onClick={handleResendOTP}
                className="text-sm font-medium text-link hover:underline"
              >
                Resend Code
              </Link>
            </p>
          </div>
        </div>
      </div>
    </main>
  );
};

export default Page;
