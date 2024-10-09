"use client";
import { Divider } from "@tremor/react";
import { FiX } from "react-icons/fi";
import { IconProps, XIcon } from "./icons/icons";
import { useRef } from "react";
import { isEventWithinRef } from "@/lib/contains";

interface ModalProps {
  icon?: ({ size, className }: IconProps) => JSX.Element;
  children: JSX.Element | string;
  title?: JSX.Element | string;
  onOutsideClick?: () => void;
  className?: string;
  width?: string;
  titleSize?: string;
  hideDividerForTitle?: boolean;
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
}: ModalProps) {
  const modalRef = useRef<HTMLDivElement>(null);

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

  return (
    <div
      onMouseDown={handleMouseDown}
      className={`fixed inset-0 bg-black bg-opacity-25 backdrop-blur-sm h-full
        flex items-center justify-center z-50 transition-opacity duration-300 ease-in-out`}
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
          ${width ?? "w-11/12 max-w-5xl"}
          ${noPadding ? "" : "p-10"}
          ${className || ""}`}
      >
        {onOutsideClick && (
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
              {!hideDividerForTitle && <Divider />}
            </>
          )}
          {children}
        </div>
      </div>
    </div>
  );
}
