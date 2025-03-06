"use client";

import { redirect } from "next/navigation";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import { MinimalUserInfo } from "@/lib/types";
import Text from "@/components/ui/text";
import { Logo } from "@/components/logo/Logo";
import { completeTenantSetup } from "@/lib/tenant";
import { useEffect, useState, useRef } from "react";
import {
  Card,
  CardContent,
  CardHeader,
  CardFooter,
} from "@/components/ui/card";
import { LoadingSpinner } from "@/app/chat/chat_search/LoadingSpinner";
import { Button } from "@/components/ui/button";
import { logout } from "@/lib/user";
import { FiLogOut } from "react-icons/fi";

export default function WaitingOnSetupPage({
  minimalUserInfo,
}: {
  minimalUserInfo: MinimalUserInfo;
}) {
  const [progress, setProgress] = useState(0);
  const [setupStage, setSetupStage] = useState<string>(
    "Setting up your account"
  );
  const progressRef = useRef<number>(0);
  const animationRef = useRef<number>();
  const startTimeRef = useRef<number>(Date.now());
  const [isReady, setIsReady] = useState(false);
  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null);

  // Setup stages that will cycle through during the loading process
  const setupStages = [
    "Setting up your account",
    "Configuring workspace",
    "Preparing resources",
    "Setting up permissions",
    "Finalizing setup",
  ];

  // Function to poll the /api/me endpoint
  const pollAccountStatus = async () => {
    try {
      const response = await fetch("/api/me");
      if (response.status === 200) {
        // Account is ready
        setIsReady(true);
        if (pollIntervalRef.current) {
          clearInterval(pollIntervalRef.current);
        }
        return true;
      }
    } catch (error) {
      console.error("Error polling account status:", error);
    }
    return false;
  };

  // Handle logout
  const handleLogout = async () => {
    try {
      await logout();
      window.location.href = "/auth/login";
    } catch (error) {
      console.error("Failed to logout:", error);
    }
  };

  useEffect(() => {
    // Animation setup for progress bar
    let lastUpdateTime = 0;
    const updateInterval = 100;
    const normalAnimationDuration = 30000; // 30 seconds for normal animation
    const acceleratedAnimationDuration = 1500; // 1.5 seconds for accelerated animation after ready
    let currentStageIndex = 0;
    let lastStageUpdateTime = Date.now();
    const stageRotationInterval = 3000; // Rotate stages every 3 seconds

    const animate = (timestamp: number) => {
      const elapsedTime = timestamp - startTimeRef.current;
      const now = Date.now();

      // Calculate progress using different curves based on ready status
      const maxProgress = 99;
      let progress;

      if (isReady) {
        // Accelerate to 100% when account is ready
        progress =
          maxProgress +
          (100 - maxProgress) *
            ((now - startTimeRef.current) / acceleratedAnimationDuration);
        if (progress >= 100) progress = 100;
      } else {
        // Slower progress when still waiting
        progress =
          maxProgress * (1 - Math.exp(-elapsedTime / normalAnimationDuration));
      }

      // Update progress if enough time has passed
      if (timestamp - lastUpdateTime > updateInterval) {
        progressRef.current = progress;
        setProgress(Math.round(progress * 10) / 10);

        // Cycle through setup stages
        if (now - lastStageUpdateTime > stageRotationInterval && !isReady) {
          currentStageIndex = (currentStageIndex + 1) % setupStages.length;
          setSetupStage(setupStages[currentStageIndex]);
          lastStageUpdateTime = now;
        }

        lastUpdateTime = timestamp;
      }

      // Continue animation if not completed
      if (progress < 100) {
        animationRef.current = requestAnimationFrame(animate);
      } else if (progress >= 100) {
        // Redirect when progress reaches 100%
        setSetupStage("Setup complete!");
        setTimeout(() => {
          window.location.href = "/chat";
        }, 500);
      }
    };

    // Start animation
    startTimeRef.current = performance.now();
    animationRef.current = requestAnimationFrame(animate);

    // Start polling the /api/me endpoint
    pollIntervalRef.current = setInterval(async () => {
      const ready = await pollAccountStatus();
      if (ready) {
        // If ready, we'll let the animation handle the redirect
        console.log("Account is ready!");
      }
    }, 2000); // Poll every 2 seconds

    // Attempt to complete tenant setup
    // completeTenantSetup(minimalUserInfo.email).catch((error) => {
    //   console.error("Failed to complete tenant setup:", error);
    // });

    // Cleanup function
    return () => {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }
    };
  }, [isReady, minimalUserInfo.email]);
  useEffect(() => {
    completeTenantSetup(minimalUserInfo.email).catch((error) => {
      console.error("Failed to complete tenant setup:", error);
    });
  }, []);

  return (
    <main className="min-h-screen bg-gradient-to-b from-white to-neutral-50 dark:from-neutral-900 dark:to-neutral-950">
      <div className="absolute top-0 w-full">
        <HealthCheckBanner />
      </div>
      <div className="min-h-screen flex items-center justify-center py-12 px-4 sm:px-6 lg:px-8">
        <div className="w-full max-w-md">
          <div className="flex flex-col items-center mb-8">
            <Logo height={80} width={80} className="mx-auto w-fit mb-6" />
            <h1 className="text-2xl font-bold text-neutral-900 dark:text-white">
              Account Setup
            </h1>
          </div>

          <Card className="border-neutral-200 dark:border-neutral-800 shadow-lg">
            <CardHeader className="pb-0">
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-3">
                  <div className="relative">
                    <LoadingSpinner size="medium" className="text-primary" />
                  </div>
                  <h2 className="text-lg font-semibold text-neutral-800 dark:text-neutral-200">
                    {setupStage}
                  </h2>
                </div>
                <span className="text-sm font-medium text-neutral-500 dark:text-neutral-400">
                  {progress}%
                </span>
              </div>
            </CardHeader>
            <CardContent className="pt-4">
              {/* Progress bar */}
              <div className="w-full h-2 bg-neutral-200 dark:bg-neutral-700 rounded-full mb-6 overflow-hidden">
                <div
                  className="h-full bg-blue-600 dark:bg-blue-500 rounded-full transition-all duration-300 ease-out"
                  style={{ width: `${progress}%` }}
                />
              </div>

              <div className="space-y-4">
                <div className="flex flex-col space-y-1">
                  <Text className="text-neutral-800 dark:text-neutral-200 font-medium">
                    Welcome,{" "}
                    <span className="font-semibold">
                      {minimalUserInfo?.email}
                    </span>
                  </Text>
                  <Text className="text-neutral-600 dark:text-neutral-400 text-sm">
                    We're setting up your account. This may take a few moments.
                  </Text>
                </div>

                <div className="bg-blue-50 dark:bg-blue-900/20 rounded-lg p-4 border border-blue-100 dark:border-blue-800">
                  <Text className="text-sm text-blue-700 dark:text-blue-300">
                    You'll be redirected automatically when your account is
                    ready. If you're not redirected within a minute, please
                    refresh the page.
                  </Text>
                </div>
              </div>
            </CardContent>
            <CardFooter className="flex justify-end pt-4">
              <Button
                variant="outline"
                size="sm"
                onClick={handleLogout}
                className="text-neutral-600 dark:text-neutral-300"
              >
                <FiLogOut className="mr-1" />
                Logout
              </Button>
            </CardFooter>
          </Card>
        </div>
      </div>
    </main>
  );
}
