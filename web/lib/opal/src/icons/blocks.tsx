import type { IconProps } from "@opal/types";
const SvgBlocks = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    fill="none"
    strokeWidth={1.5}
    strokeLinecap="round"
    strokeLinejoin="round"
    className="lucide lucide-blocks-icon lucide-blocks"
    stroke="currentColor"
    {...props}
  >
    <path d="M10 22V7a1 1 0 0 0-1-1H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-5a1 1 0 0 0-1-1H2" />
    <rect x={14} y={2} rx={1} />
  </svg>
);
export default SvgBlocks;
