import { Divider } from "@tremor/react";
import { FiX } from "react-icons/fi";
import { IconProps } from "./icons/icons";

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
  icon,
  children,
  title,
  onOutsideClick,
  className,
  width,
  titleSize,
  hideDividerForTitle,
  noPadding,
}: ModalProps) {
  return (
    <div>
      <div
        className={`
        fixed inset-0 bg-black bg-opacity-30 backdrop-blur-sm
        flex items-center justify-center z-50
      `}
        onClick={onOutsideClick}
      >
        <div
          className={`
          bg-background rounded shadow-lg
          relative ${width ?? "w-1/2"} text-sm 
          ${noPadding ? "" : "p-8"}
          ${className}
        `}
          onClick={(event) => event.stopPropagation()}
        >
          {title && (
            <>
              <div className="flex mb-4">
                <h2
                  className={
                    "my-auto flex content-start gap-x-4 font-bold " +
                    (titleSize || "text-2xl")
                  }
                >
                  {title}
                  {icon && icon({ size: 30 })}
                </h2>

                {onOutsideClick && (
                  <div
                    onClick={onOutsideClick}
                    className="my-auto ml-auto p-2 hover:bg-hover rounded cursor-pointer"
                  >
                    <FiX size={20} />
                  </div>
                )}
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
