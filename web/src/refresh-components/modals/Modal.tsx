import React, { useRef } from "react";
import Text from "@/refresh-components/texts/Text";
import SvgX from "@/icons/x";
import {
  ModalIds,
  useChatModal,
} from "@/refresh-components/contexts/ChatModalContext";
import IconButton from "@/refresh-components/buttons/IconButton";
import { cn } from "@/lib/utils";
import { SvgProps } from "@/icons";
import CoreModal from "@/refresh-components/modals/CoreModal";

interface ModalProps {
  // Modal sizes
  sm?: boolean;
  xs?: boolean;

  // Modal configurations
  clickOutsideToClose?: boolean;

  // Base modal props
  id: ModalIds;
  icon: React.FunctionComponent<SvgProps>;
  title: string;
  description?: string;
  className?: string;
  children?: React.ReactNode;
}

export default function Modal({
  sm,
  xs,

  clickOutsideToClose = true,

  id,
  icon: Icon,
  title,
  description,
  children,
  className,
}: ModalProps) {
  const { isOpen, toggleModal } = useChatModal();
  const insideModal = useRef(false);

  if (!isOpen(id)) return null;

  return (
    <CoreModal
      className={cn(
        "w-[80dvw] h-[80dvh]",
        sm && "max-w-[60rem]",
        xs && "max-w-[32rem] h-fit",
        className
      )}
      onClickOutside={
        clickOutsideToClose
          ? () => {
              if (insideModal.current) return;
              toggleModal(id, false);
            }
          : undefined
      }
    >
      <div className="flex flex-col gap-spacing-interline p-spacing-paragraph">
        <div className="flex flex-row items-center justify-between">
          <Icon className="w-[1.5rem] h-[1.5rem] stroke-text-04" />
          <div data-testid="Modal/close-modal">
            <IconButton
              icon={SvgX}
              internal
              onClick={() => toggleModal(id, false)}
            />
          </div>
        </div>
        <Text headingH3>{title}</Text>
        {description && (
          <Text secondaryBody text02>
            {description}
          </Text>
        )}
      </div>
      {children}
    </CoreModal>
  );
}
