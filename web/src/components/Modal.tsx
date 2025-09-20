"use client";

import { Separator } from "@/components/ui/separator";
import { IconProps, XIcon } from "./icons/icons";
import { useRef } from "react";
import ReactDOM from "react-dom";
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

interface ModalProps {
  icon?: ({ size, className }: IconProps) => JSX.Element;
  children?: React.ReactNode;
  title?: React.ReactNode;
  onOutsideClick?: () => void;
  className?: string;
  width?: string;
  titleSize?: string;
  hideDividerForTitle?: boolean;
  hideCloseButton?: boolean;
  noPadding?: boolean;
  height?: string;
  noScroll?: boolean;
  heightOverride?: string;
  removeBottomPadding?: boolean;
  removePadding?: boolean;
  increasedPadding?: boolean;
  hideOverflow?: boolean;
}

export function Modal({
  children,
  title,
  onOutsideClick,
  className,
  width,
  titleSize,
  hideDividerForTitle,
  noPadding,
  icon,
  hideCloseButton,
  heightOverride,
  removeBottomPadding,
  increasedPadding,
  hideOverflow,
}: ModalProps) {
  const modalRef = useRef<HTMLDivElement>(null);
  const [isMounted, setIsMounted] = useState(false);

  useEffect(() => {
    setIsMounted(true);
    return () => {
      setIsMounted(false);
    };
  }, []);

  function handleMouseDown(e: React.MouseEvent<HTMLDivElement>) {
    // Only close if the user clicked exactly on the overlay (and not on a child element).
    if (onOutsideClick && e.target === e.currentTarget) {
      onOutsideClick();
    }
  }

  const modalContent = (
    <div
      onMouseDown={handleMouseDown}
      className={cn(
        `fixed inset-0 bg-mask-01 border bg-opacity-30 backdrop-blur-md h-full flex items-center justify-center z-50 transition-opacity duration-300 ease-in-out`
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
          bg-background-tint-02
          rounded-08
          shadow-2xl
          transform
          transition-all
          duration-300
          ease-in-out
          relative
          ${width ?? "w-11/12 max-w-4xl"}
          ${noPadding ? "" : removeBottomPadding ? "pt-8 px-8" : "p-8"}
          ${className || ""}
          flex
          flex-col
          ${heightOverride ? `h-${heightOverride}` : "max-h-[90vh]"}
          ${hideOverflow ? "overflow-hidden" : "overflow-visible"}
        `}
      >
        {onOutsideClick && !hideCloseButton && (
          <div className="absolute top-2 right-2">
            <button
              onClick={onOutsideClick}
              className="cursor-pointer transition-colors duration-200 p-2"
              aria-label="Close modal"
            >
              <XIcon className="w-5 h-5" />
            </button>
          </div>
        )}
        <div className="items-start flex-shrink-0">
          {title && (
            <>
              <div className="flex">
                <h2
                  className={`my-auto flex content-start gap-x-4 font-bold ${
                    titleSize || "text-2xl"
                  } ${increasedPadding && "px-6"}`}
                >
                  {title}
                  {icon && icon({ size: 30 })}
                </h2>
              </div>
              {!hideDividerForTitle ? <Separator /> : <div className="my-4" />}
            </>
          )}
        </div>
        {children}
      </div>
    </div>
  );

  return isMounted ? ReactDOM.createPortal(modalContent, document.body) : null;
}
