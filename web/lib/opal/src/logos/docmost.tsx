import type { IconProps } from "@opal/types";
// DocMost brand mark: white glyph on a rounded black square.
// Colors use Opal CSS vars so the logo inverts cleanly in dark mode
// (square text-05 -> light, glyph text-inverted-05 -> dark), matching
// how the other monochrome brand logos (e.g. Notion) are handled.
const SvgDocmost = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 512 512"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <rect
      x={0}
      y={0}
      width={512}
      height={512}
      rx={115}
      fill="var(--text-05)"
    />
    {/* Left stem with kicked-out foot */}
    <path
      d="M110 165Q110 110 165 110L182 110Q224 110 224 165L224 300L326 396Q344 414 326 430Q310 442 292 425L168 426Q110 426 110 374Z"
      fill="var(--text-inverted-05)"
    />
    {/* Upper-right hook forming the bowl */}
    <path
      d="M252 158Q358 104 414 182Q452 240 418 304Q398 344 356 354L350 304Q384 296 396 256Q412 206 360 180Q322 158 272 200Z"
      fill="var(--text-inverted-05)"
    />
  </svg>
);
export default SvgDocmost;
