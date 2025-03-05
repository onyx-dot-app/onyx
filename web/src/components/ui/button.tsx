import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex cursor-pointer items-center justify-center gap-2 whitespace-nowrap rounded text-sm font-medium ring-offset-[#fff] transition-colors focus-visible:outline-none  disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        agent:
          "bg-agent text-white hover:bg-agent-hovered dark:bg-agent dark:text-white dark:hover:bg-agent/90",
        success:
          "bg-green-100 text-green-600 hover:bg-green-500/90 dark:bg-green-700 dark:text-green-100 dark:hover:bg-green-600/90",
        "success-reverse":
          "bg-green-600 text-[#fff] hover:bg-green-700 dark:bg-green-700 dark:text-green-100 dark:hover:bg-green-600",
        default:
          "bg-neutral-900 border-border text-neutral-50 hover:bg-neutral-900/90 dark:bg-neutral-100 dark:text-neutral-900 dark:hover:bg-neutral-200",
        "default-reverse":
          "bg-neutral-50 border-border text-neutral-900 hover:bg-neutral-50/90 dark:bg-neutral-800 dark:text-neutral-50 dark:hover:bg-neutral-700",
        destructive:
          "bg-red-500 text-neutral-50 hover:bg-red-500/90 dark:bg-red-700 dark:hover:bg-red-600",
        "destructive-reverse":
          "bg-neutral-50 text-red-500 hover:bg-neutral-50/90 dark:bg-red-100 dark:text-red-700 dark:hover:bg-red-200",
        outline:
          "border border-neutral-300 bg-[#fff] hover:bg-neutral-50 hover:text-neutral-900 dark:border-neutral-600 dark:bg-neutral-800 dark:hover:bg-neutral-700 dark:hover:text-neutral-50",
        create:
          "border border-neutral-300 bg-neutral-50 text-neutral-700 hover:bg-neutral-100 hover:text-neutral-900 transition-colors duration-200 ease-in-out shadow-sm dark:border-neutral-600 dark:bg-neutral-800 dark:text-neutral-200 dark:hover:bg-neutral-700 dark:hover:text-neutral-50",
        "outline-reverse":
          "border border-neutral-300 bg-neutral-900 hover:bg-neutral-800 hover:text-neutral-50 dark:border-neutral-600 dark:bg-neutral-100 dark:hover:bg-neutral-200 dark:hover:text-neutral-900",
        secondary:
          "bg-neutral-100 text-neutral-900 hover:bg-neutral-100/80 dark:bg-neutral-700 dark:text-neutral-100 dark:hover:bg-neutral-600",
        "secondary-reverse":
          "bg-neutral-900 text-neutral-100 hover:bg-neutral-900/80 dark:bg-neutral-200 dark:text-neutral-800 dark:hover:bg-neutral-300",
        ghost:
          "hover:bg-neutral-100 hover:text-neutral-900 dark:hover:bg-transparent dark:hover:text-neutral-50",
        "ghost-reverse":
          "hover:bg-neutral-800 hover:text-neutral-50 dark:hover:bg-neutral-200 dark:hover:text-neutral-900",
        link: "text-neutral-900 underline-offset-4 hover:underline dark:text-neutral-100",
        "link-reverse":
          "text-neutral-50 underline-offset-4 hover:underline dark:text-neutral-900",
        submit:
          "bg-green-500 text-neutral-50 hover:bg-green-600/90 dark:bg-green-700 dark:hover:bg-green-600",
        "submit-reverse":
          "bg-neutral-50 text-blue-600 hover:bg-neutral-50/80 dark:bg-blue-100 dark:text-blue-800 dark:hover:bg-blue-200",
        navigate:
          "bg-blue-500 text-[#fff] hover:bg-blue-600 dark:bg-blue-700 dark:hover:bg-blue-600",
        "navigate-reverse":
          "bg-[#fff] text-blue-500 hover:bg-blue-50 dark:bg-blue-100 dark:text-blue-800 dark:hover:bg-blue-200",
        update:
          "border border-neutral-300 bg-neutral-100 text-neutral-900 hover:bg-neutral-100/80 dark:border-neutral-600 dark:bg-neutral-700 dark:text-neutral-100 dark:hover:bg-neutral-600",
        "update-reverse":
          "bg-neutral-900 text-neutral-100 hover:bg-neutral-900/80 dark:bg-neutral-200 dark:text-neutral-800 dark:hover:bg-neutral-300",
        next: "bg-neutral-700 text-neutral-50 hover:bg-neutral-700/90 dark:bg-neutral-300 dark:text-neutral-900 dark:hover:bg-neutral-400",
        "next-reverse":
          "bg-neutral-50 text-neutral-700 hover:bg-neutral-50/90 dark:bg-neutral-800 dark:text-neutral-200 dark:hover:bg-neutral-700",
      },
      size: {
        default: "h-10 px-4 py-2",
        xs: "h-8 px-3 py-1",
        sm: "h-9 px-3",
        lg: "h-11 px-8",
        icon: "h-10 w-10",
      },
      reverse: {
        true: "",
        false: "",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
);

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  icon?: React.ElementType;
  tooltip?: string;
  reverse?: boolean;
}
const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      className,
      variant,
      size = "sm",
      asChild = false,
      icon: Icon,
      tooltip,
      ...props
    },
    ref
  ) => {
    const Comp = asChild ? Slot : "button";
    const button = (
      <Comp
        className={cn(
          buttonVariants({
            variant,
            size,
            className,
          })
        )}
        ref={ref}
        {...props}
      >
        {Icon && <Icon />}
        {props.children}
      </Comp>
    );

    if (tooltip) {
      return (
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger>
              <div>{button}</div>
            </TooltipTrigger>
            <TooltipContent showTick={true}>
              <p>{tooltip}</p>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      );
    }

    return button;
  }
);
Button.displayName = "Button";

export { Button, buttonVariants };
