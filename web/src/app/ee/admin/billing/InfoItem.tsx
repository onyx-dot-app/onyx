import React from "react";

interface InfoItemProps {
  title: string;
  value: string;
}

export function InfoItem({ title, value }: InfoItemProps) {
  return (
    <div className="bg-muted p-4 rounded-lg">
      <p className="text-sm font-medium text-muted-foreground mb-1">{title}</p>
      <p className="text-lg font-semibold text-foreground dark:text-neutral-100">
        {value}
      </p>
    </div>
  );
}
