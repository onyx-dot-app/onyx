import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-normal transition-colors focus:outline-none focus:ring-2 focus:ring-neutral-950 focus:ring-offset-2 dark:focus:ring-neutral-300",
  {
    variants: {
      variant: {
        invalid:
          "border-orange-200 bg-orange-50 text-orange-600 dark:border-orange-700 dark:bg-orange-900 dark:text-orange-50",
        outline:
          "border-neutral-200 bg-neutral-50 text-neutral-600 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-50",
        purple:
          "border-purple-200 bg-purple-50 text-purple-700 dark:border-purple-700 dark:bg-purple-900 dark:text-purple-100",
        public:
          "border-green-200 bg-green-50 text-green-700 dark:border-green-700 dark:bg-green-900 dark:text-green-100",
        private:
          "border-yellow-200 bg-yellow-50 text-yellow-700 dark:border-yellow-600 dark:bg-yellow-700 dark:text-yellow-100",
        "auto-sync":
          "border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-700 dark:bg-blue-900 dark:text-blue-100",
        agent:
          "border-orange-200 bg-orange-50 text-orange-600 dark:border-orange-800 dark:bg-orange-600/20 dark:text-neutral-200",
        "agent-faded":
          "border-neutral-200 bg-neutral-50 text-neutral-600 dark:border-neutral-700 dark:bg-neutral-800 dark:text-neutral-50",
        canceled:
          "border-gray-200 bg-gray-50 text-gray-600 dark:border-gray-700 dark:bg-gray-900 dark:text-neutral-50",
        paused:
          "border-yellow-200 bg-yellow-50 text-yellow-700 dark:border-yellow-600 dark:bg-yellow-700 dark:text-yellow-100",
        in_progress:
          "border-blue-200 bg-blue-50 text-blue-600 dark:border-blue-700 dark:bg-blue-900 dark:text-neutral-50",
        success:
          "border-green-200 bg-emerald-50 text-green-600 dark:border-green-600 dark:bg-green-900 dark:text-green-50",
        default:
          "border-neutral-200 bg-neutral-50 text-neutral-600 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-50",
        secondary:
          "border-neutral-200 bg-neutral-50 text-neutral-600 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-50",
        destructive:
          "border-red-200 bg-red-50 text-red-600 dark:border-red-700 dark:bg-red-900 dark:text-neutral-50",
        not_started:
          "border-purple-200 bg-purple-50 text-purple-700 dark:border-purple-700 dark:bg-purple-900 dark:text-purple-100",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({
  className,
  variant,
  color,
  icon: Icon,
  size = "sm",
  circle,
  tooltip,
  ...props
}: BadgeProps & {
  icon?: React.ElementType;
  size?: "sm" | "md" | "xs";
  circle?: boolean;
  tooltip?: string;
}) {
  const sizeClasses = {
    sm: "px-2.5 py-0.5 text-xs",
    md: "px-3 py-1 text-sm",
    xs: "px-1.5 py-0.25 text-[.5rem]",
  };

  const BadgeContent = (
    <div
      className={cn(
        "flex-none inline-flex items-center whitespace-nowrap overflow-hidden",
        badgeVariants({ variant }),
        sizeClasses[size],
        className
      )}
      {...props}
    >
      {Icon && (
        <Icon
          className={cn(
            "mr-1 flex-shrink-0",
            size === "sm" ? "h-3 w-3" : size === "xs" ? "h-2 w-2" : "h-4 w-4"
          )}
        />
      )}
      {circle && (
        <div
          className={cn(
            "mr-2 rounded-full bg-current opacity-80 flex-shrink-0",
            size === "xs" ? "h-2 w-2" : "h-2.5 w-2.5"
          )}
        />
      )}
      <span className="truncate">{props.children}</span>
    </div>
  );

  if (tooltip) {
    return (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>{BadgeContent}</TooltipTrigger>
          <TooltipContent>
            <p>{tooltip}</p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  return BadgeContent;
}

export { Badge, badgeVariants };
