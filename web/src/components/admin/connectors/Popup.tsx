import { useCallback, useRef, useState } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";
import { Check } from "lucide-react";
import { Warning } from "@phosphor-icons/react";
import { NEXT_PUBLIC_INCLUDE_ERROR_POPUP_SUPPORT_LINK } from "@/lib/constants";

const popupVariants = cva(
  "fixed bottom-4 left-4 p-4 rounded-lg shadow-xl text-[#fff] z-[10000] flex items-center space-x-3 transition-all duration-300 ease-in-out",
  {
    variants: {
      type: {
        success: "bg-green-500 dark:bg-green-600",
        error: "bg-red-500 dark:bg-red-600",
        info: "bg-blue-500 dark:bg-blue-600",
        warning: "bg-yellow-500 dark:bg-yellow-600",
      },
    },
    defaultVariants: {
      type: "info",
    },
  }
);

export interface PopupSpec extends VariantProps<typeof popupVariants> {
  message: string;
}

export const Popup: React.FC<PopupSpec> = ({ message, type }) => (
  <div className={cn(popupVariants({ type }))}>
    {type === "success" ? (
      <Check className="w-6 h-6" />
    ) : type === "error" ? (
      <Warning className="w-6 h-6 " />
    ) : type === "info" ? (
      <svg
        className="w-6 h-6"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
        />
      </svg>
    ) : (
      <svg
        className="w-6 h-6"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
        />
      </svg>
    )}
    <div className="flex flex-col justify-center items-start">
      <p className="font-medium">{message}</p>
      {type === "error" && NEXT_PUBLIC_INCLUDE_ERROR_POPUP_SUPPORT_LINK && (
        <p className="text-xs">
          Need help?{" "}
          <a
            href="https://discord.gg/4NA5SbzrWb"
            target="_blank"
            rel="noopener noreferrer"
            className="underline hover:text-red-100 dark:hover:text-red-200"
          >
            Join our community
          </a>{" "}
          for support!
        </p>
      )}
    </div>
  </div>
);

export const usePopup = () => {
  const [popup, setPopup] = useState<PopupSpec | null>(null);
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);

  const setPopupWithExpiration = useCallback((popupSpec: PopupSpec | null) => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }

    setPopup(popupSpec);

    if (popupSpec) {
      timeoutRef.current = setTimeout(() => {
        setPopup(null);
      }, 4000);
    }
  }, []);

  return {
    popup: popup && <Popup {...popup} />,
    setPopup: setPopupWithExpiration,
  };
};
