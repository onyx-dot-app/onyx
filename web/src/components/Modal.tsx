"use client";
import { Separator } from "@/components/ui/separator";
import { IconProps, XIcon } from "./icons/icons";
import { useRef } from "react";
import { isEventWithinRef } from "@/lib/contains";
import ReactDOM from "react-dom";
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

interface ModalProps {
  icon?: ({ size, className }: IconProps) => JSX.Element;
  children: JSX.Element | string;
  title?: JSX.Element | string;
  onOutsideClick?: () => void;
  className?: string;
  width?: string;
  titleSize?: string;
  hideDividerForTitle?: boolean;
  hideCloseButton?: boolean;
  noPadding?: boolean;
  height?: string;
  noScroll?: boolean;
}

export function Modal({
  children,
  title,
  onOutsideClick,
  className,
  width,
  titleSize,
  hideDividerForTitle,
  height,
  noPadding,
  icon,
  hideCloseButton,
  noScroll,
}: ModalProps) {
  const modalRef = useRef<HTMLDivElement>(null);
  const [isMounted, setIsMounted] = useState(false);

  useEffect(() => {
    setIsMounted(true);
    return () => {
      setIsMounted(false);
    };
  }, []);

  const handleMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    // Only close if the user clicked exactly on the overlay (and not on a child element).
    if (onOutsideClick && e.target === e.currentTarget) {
      onOutsideClick();
    }
  };

  const modalContent = (
    <div
      onMouseDown={handleMouseDown}
      className={cn(
        `fixed inset-0 bg-black bg-opacity-25 backdrop-blur-sm h-full
        flex items-center justify-center z-[9999] transition-opacity duration-300 ease-in-out`
      )}
    >
      <div
        ref={modalRef}
        onClick={(e) => {
          if (onOutsideClick) {
            e.stopPropagation();
          }
        }}
        className={`
          bg-background 
          text-emphasis 
          rounded 
          shadow-2xl 
          transform 
          transition-all 
          duration-300 
          ease-in-out
          relative
          overflow-visible
          ${width ?? "w-11/12 max-w-4xl"}
          ${noPadding ? "" : "p-10"}
          ${className || ""}
        `}
      >
        {onOutsideClick && !hideCloseButton && (
          <div className="absolute top-2 right-2">
            <button
              onClick={onOutsideClick}
              className="cursor-pointer text-text-500 hover:text-text-700 transition-colors duration-200 p-2"
              aria-label="Close modal"
            >
              <XIcon className="w-5 h-5" />
            </button>
          </div>
        )}
        <div className="w-full overflow-y-auto overflow-x-visible p-1 flex flex-col h-full justify-stretch">
          {title && (
            <>
              <div className="flex mb-4">
                <h2
                  className={`my-auto flex content-start gap-x-4 font-bold ${
                    titleSize || "text-2xl"
                  }`}
                >
                  {title}
                  {icon && icon({ size: 30 })}
                </h2>
              </div>
              {!hideDividerForTitle && <Separator />}
            </>
          )}
          <div
            className={cn(
              noScroll ? "overflow-auto" : "overflow-x-visible",
              height || "max-h-[60vh]"
            )}
          >
            {children}
          </div>
        </div>
      </div>
    </div>
  );

  return isMounted ? ReactDOM.createPortal(modalContent, document.body) : null;
}
