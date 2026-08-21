import type { IconProps } from "@opal/types";
const SvgKeenable = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 52 52"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <rect width={52} height={52} rx={11} fill="#3B5BFE" />
    <circle cx={22} cy={22} r={9} stroke="#fff" strokeWidth={3.4} />
    <line
      x1={28.4}
      y1={28.4}
      x2={39}
      y2={39}
      stroke="#fff"
      strokeWidth={3.4}
      strokeLinecap="round"
    />
  </svg>
);
export default SvgKeenable;
