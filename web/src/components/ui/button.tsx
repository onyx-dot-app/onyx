import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex cursor-pointer items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium ring-offset-white transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-950 focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0 dark:ring-offset-neutral-950 dark:focus-visible:ring-neutral-300",
  {
    variants: {
      variant: {
        success:
          "bg-green-100 text-green-600 hover:bg-green-500/90 dark:bg-blue-500 dark:text-neutral-50 dark:hover:bg-green-900/90",
        "success-reverse":
          "bg-green-500 text-inverted hover:bg-green-600/90 dark:bg-neutral-50 dark:text-blue-500 dark:hover:bg-green-100/90",

        default:
          "bg-neutral-900 border-border text-neutral-50 hover:bg-neutral-900/90 dark:bg-neutral-50 dark:text-neutral-900 dark:hover:bg-neutral-50/90",
        "default-reverse":
          "bg-neutral-50 border-border text-neutral-900 hover:bg-neutral-50/90 dark:bg-neutral-900 dark:text-neutral-50 dark:hover:bg-neutral-900/90",
        destructive:
          "bg-red-500 text-neutral-50 hover:bg-red-500/90 dark:bg-red-900 dark:text-neutral-50 dark:hover:bg-red-900/90",
        "destructive-reverse":
          "bg-neutral-50 text-red-500 hover:bg-neutral-50/90 dark:bg-neutral-50 dark:text-red-900 dark:hover:bg-neutral-50/90",
        outline:
          "border border-neutral-300 bg-white hover:bg-neutral-50 hover:text-neutral-900 dark:border-neutral-800 dark:bg-neutral-950 dark:hover:bg-neutral-800 dark:hover:text-neutral-50",
        "outline-reverse":
          "border border-neutral-300 bg-neutral-900 hover:bg-neutral-800 hover:text-neutral-50 dark:border-neutral-800 dark:bg-white dark:hover:bg-neutral-50 dark:hover:text-neutral-900",
        secondary:
          "bg-neutral-100 text-neutral-900 hover:bg-neutral-100/80 dark:bg-neutral-800 dark:text-neutral-50 dark:hover:bg-neutral-800/80",
        "secondary-reverse":
          "bg-neutral-900 text-neutral-100 hover:bg-neutral-900/80 dark:bg-neutral-50 dark:text-neutral-800 dark:hover:bg-neutral-50/80",
        ghost:
          "hover:bg-neutral-100 hover:text-neutral-900 dark:hover:bg-neutral-800 dark:hover:text-neutral-50",
        "ghost-reverse":
          "hover:bg-neutral-800 hover:text-neutral-50 dark:hover:bg-neutral-100 dark:hover:text-neutral-900",
        link: "text-neutral-900 underline-offset-4 hover:underline dark:text-neutral-50",
        "link-reverse":
          "text-neutral-50 underline-offset-4 hover:underline dark:text-neutral-900",
        submit:
          "bg-green-500 text-inverted hover:bg-green-600/90 dark:bg-neutral-50 dark:text-blue-500 dark:hover:bg-green-100/90",

        // "bg-blue-600 text-neutral-50 hover:bg-blue-600/80 dark:bg-blue-600 dark:text-neutral-50 dark:hover:bg-blue-600/90",
        "submit-reverse":
          "bg-neutral-50 text-blue-600 hover:bg-neutral-50/80 dark:bg-neutral-50 dark:text-blue-600 dark:hover:bg-neutral-50/90",
        navigate:
          "bg-blue-500 text-white hover:bg-blue-600 dark:bg-blue-600 dark:hover:bg-blue-700",
        "navigate-reverse":
          "bg-white text-blue-500 hover:bg-blue-50 dark:bg-blue-100 dark:hover:bg-blue-200",
        update:
          "border border-neutral-300 bg-neutral-100 text-neutral-900 hover:bg-neutral-100/80 dark:bg-neutral-800 dark:text-neutral-50 dark:hover:bg-neutral-800/80",
        "update-reverse":
          "bg-neutral-900 text-neutral-100 hover:bg-neutral-900/80 dark:bg-neutral-50 dark:text-neutral-800 dark:hover:bg-neutral-50/80",
        next: "bg-neutral-700 text-neutral-50 hover:bg-neutral-700/90 dark:bg-neutral-600 dark:text-neutral-50 dark:hover:bg-neutral-600/90",
        "next-reverse":
          "bg-neutral-50 text-neutral-700 hover:bg-neutral-50/90 dark:bg-neutral-50 dark:text-neutral-600 dark:hover:bg-neutral-50/90",
      },
      size: {
        default: "h-10 px-4 py-2",
        sm: "h-9 rounded-md px-3",
        lg: "h-11 rounded-md px-8",
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
        <div className="relative group">
          {button}
          <div className="absolute bottom-full left-1/2 transform -translate-x-1/2 mb-2 px-2 py-1 bg-neutral-800 text-white text-sm rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap">
            {tooltip}
          </div>
        </div>
      );
    }

    return button;
  }
);
Button.displayName = "Button";

export { Button, buttonVariants };
