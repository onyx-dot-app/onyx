import React, { useRef } from "react";
import Text from "@/components-2/Text";
import SvgX from "@/icons/x";
import { ModalIds, useModal } from "@/components-2/context/ModalContext";

interface ModalProps {
  id: ModalIds;
  title: string;
  clickOutsideToClose?: boolean;
  mini?: boolean;
  className?: string;
  children?: React.ReactNode;
}

export default function Modal({
  id,
  title,
  clickOutsideToClose = true,
  mini,
  children,
  className,
}: ModalProps) {
  const { isOpen, toggleModal } = useModal();
  const outsideModal = useRef(false);

  if (!isOpen(id)) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-mask-03 backdrop-blur-md"
      onClick={
        clickOutsideToClose
          ? () => {
              if (outsideModal.current) {
                toggleModal(id, false);
              }
            }
          : undefined
      }
    >
      <div
        className={`z-10 w-[80dvw] h-[80dvh] rounded-16 border flex flex-col bg-background-tint-01 ${mini && "max-w-[60rem]"} ${className}`}
        onMouseOver={() => (outsideModal.current = false)}
        onMouseLeave={() => (outsideModal.current = true)}
      >
        {/* Header with title */}
        <div className="flex items-center justify-between p-padding-block-end">
          <Text headingH2>{title}</Text>
          <SvgX
            className="stroke-text-03 w-[1.5rem] h-[1.5rem]"
            onClick={() => toggleModal(id, false)}
          />
        </div>

        <div className="border-b" />

        {/* Content area */}
        <div className="flex-1 m-padding-block-end overflow-scroll">
          {children}
        </div>
      </div>
    </div>
  );
}
