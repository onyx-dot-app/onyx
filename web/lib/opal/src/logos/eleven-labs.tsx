import type { IconProps } from "@opal/types";
const SvgElevenLabs = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path d="M10.5 2H13V14H10.5V2Z" fill="var(--text-05)" />
    <path d="M3 2H5.5V14H3V2Z" fill="var(--text-05)" />
  </svg>
);
export default SvgElevenLabs;
