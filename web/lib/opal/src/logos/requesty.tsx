import type { IconProps } from "@opal/types";

const SvgRequesty = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 128 128"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <title>Requesty</title>
    <g transform="rotate(-6 64 64)">
      <path
        d="M32 16h66a14 14 0 0 1 14 14v56a14 14 0 0 1-14 14H54l-18 20v-20h-4a14 14 0 0 1-14-14V30a14 14 0 0 1 14-14z"
        fill="#1677FF"
      />
      <path
        d="M40 40l20 16-20 16"
        stroke="#FFFFFF"
        strokeWidth="9"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M66 78h20"
        stroke="#FFFFFF"
        strokeWidth="9"
        strokeLinecap="round"
      />
    </g>
  </svg>
);

export default SvgRequesty;
