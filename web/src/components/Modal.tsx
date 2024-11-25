"use client";
import { Separator } from "@/components/ui/separator";
import { FiX } from "react-icons/fi";
import { IconProps, XIcon } from "./icons/icons";
import { useRef } from "react";
import { isEventWithinRef } from "@/lib/contains";
import ReactDOM from "react-dom";
import { useEffect, useState } from "react";

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
    if (
      onOutsideClick &&
      modalRef.current &&
      !modalRef.current.contains(e.target as Node) &&
      !isEventWithinRef(e.nativeEvent, modalRef)
    ) {
      onOutsideClick();
    }
  };

  const modalContent = (
    <div
      onMouseDown={handleMouseDown}
      className={`fixed inset-0 bg-black bg-opacity-25 backdrop-blur-sm h-full
        flex items-center justify-center z-[9999] transition-opacity duration-300 ease-in-out`}
    >
      <div
        ref={modalRef}
        onClick={(e) => {
          if (onOutsideClick) {
            e.stopPropagation();
          }
        }}
        className={`bg-background text-emphasis rounded shadow-2xl 
          transform transition-all duration-300 ease-in-out
          ${width ?? "w-11/12 max-w-4xl"}
          ${noPadding ? "" : "p-10"}
          ${className || ""}`}
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

        <div className="w-full flex flex-col h-full justify-stretch">
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
          <div className="max-h-[60vh] overflow-y-scroll">{children}</div>
        </div>
      </div>
    </div>
  );

  return isMounted ? ReactDOM.createPortal(modalContent, document.body) : null;
}
