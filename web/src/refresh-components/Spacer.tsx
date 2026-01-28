export interface SpacerProps {
  direction?: "horizontal" | "vertical";
  rem?: number;
}

export default function Spacer({
  direction = "vertical",
  rem = 1,
}: SpacerProps) {
  const isVertical = direction === "vertical";
  const size = `${rem}rem`;

  return (
    <div
      style={{
        height: isVertical ? size : undefined,
        width: isVertical ? undefined : size,
      }}
    />
  );
}
