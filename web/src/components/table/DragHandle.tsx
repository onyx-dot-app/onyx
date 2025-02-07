import React from "react";
import { MdDragIndicator } from "react-icons/md";

interface DragHandleProps extends React.HTMLAttributes<HTMLDivElement> {
  isDragging?: boolean;
  size?: number;
}

export const DragHandle: React.FC<DragHandleProps> = ({
  isDragging,
  size = 16,
  ...props
}) => {
  return (
    <div
      className={`flex items-center justify-center ${
        isDragging ? "cursor-grabbing" : "cursor-grab"
      }`}
      {...props}
    >
      <MdDragIndicator size={size} />
    </div>
  );
};
