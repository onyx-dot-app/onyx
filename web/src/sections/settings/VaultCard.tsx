"use client";

import { cn } from "@/lib/utils";
import { Text } from "@opal/components";
import type { UserCounter } from "@/sections/settings/interfaces";

interface VaultCardProps {
  counter: UserCounter;
}

function VaultCard({ counter }: VaultCardProps) {
  const isCompleted = counter.completed_at !== null;
  const progress = Math.min((counter.current / counter.target) * 100, 100);

  return (
    <div
      className={cn(
        "flex flex-col gap-3 rounded-lg border p-4",
        "border-border-02 bg-background-neutral-01",
        "transition-all duration-200",
        isCompleted && "border-theme-primary-04 bg-background-tint-01"
      )}
    >
      <div className="flex items-center gap-3">
        <div
          className={cn(
            "flex h-12 w-12 items-center justify-center rounded-md",
            "bg-background-neutral-03",
            !isCompleted && "grayscale opacity-40"
          )}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={`/img/vault/${counter.icon}`}
            alt=""
            className="h-8 w-8"
            style={{ imageRendering: "pixelated" }}
          />
        </div>
        <div className="flex flex-col gap-0.5">
          <Text
            font="main-ui-action"
            color={isCompleted ? "text-01" : "text-03"}
          >
            {isCompleted ? counter.title : "???"}
          </Text>
          <Text font="secondary-body" color="text-05">
            {isCompleted ? counter.description : counter.hint}
          </Text>
        </div>
      </div>

      <div className="flex flex-col gap-1">
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-background-neutral-03">
          <div
            className={cn(
              "h-full rounded-full transition-all duration-500",
              isCompleted ? "bg-theme-primary-05" : "bg-background-neutral-05"
            )}
            style={{ width: `${progress}%` }}
          />
        </div>
        <div className="flex justify-between">
          <Text font="secondary-body" color="text-05">
            {isCompleted
              ? `Completed ${new Date(
                  counter.completed_at!
                ).toLocaleDateString()}`
              : `${Math.round(progress)}%`}
          </Text>
          {!isCompleted && (
            <Text font="secondary-body" color="text-05">
              {`${counter.current} / ${counter.target}`}
            </Text>
          )}
        </div>
      </div>
    </div>
  );
}

export default VaultCard;
