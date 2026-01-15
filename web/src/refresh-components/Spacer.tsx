export interface SpacerProps {
  vertical?: boolean;
  horizontal?: boolean;
  rem?: number;
}

export default function Spacer({ vertical, horizontal, rem = 1 }: SpacerProps) {
  const isVertical = vertical ? true : horizontal ? false : true;
  const size = `${rem}rem`;

  return (
    <div
      style={{
        height: isVertical ? size : undefined,
        width: !isVertical ? size : undefined,
      }}
    />
  );
}
