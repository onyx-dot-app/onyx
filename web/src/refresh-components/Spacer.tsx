type DirectionProps = {
  vertical?: boolean;
  horizontal?: boolean;
};

export type SpacerProps = DirectionProps &
  ({ rem?: number; pixels?: never } | { pixels: number; rem?: never });

export default function Spacer({
  vertical,
  horizontal,
  rem = 1,
  pixels,
}: SpacerProps) {
  const isVertical = vertical ? true : horizontal ? false : true;
  const size = pixels !== undefined ? `${pixels}px` : `${rem}rem`;

  return (
    <div
      style={{
        height: isVertical ? size : undefined,
        width: !isVertical ? size : undefined,
      }}
    />
  );
}
