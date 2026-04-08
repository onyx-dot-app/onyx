import type { IconProps } from "@opal/types";
const SvgMistral = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 52 52"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path d="M15.5004 8H8.50043V15H15.5004V8Z" fill="#FFD800" />
    <path d="M43.5004 8H36.5004L36.5001 15H43.5004V8Z" fill="#FFD800" />
    <path d="M22.5004 15H15.5004H8.50043V22H22.5004V15Z" fill="#FFAF00" />
    <path d="M43.5004 15H36.5001H29.4998V22H43.5004V15Z" fill="#FFAF00" />
    <path
      d="M43.5004 22H29.4998H22.5004H8.50043V29H15.5004H22.5004H29.4998H36.5001H43.5004V22Z"
      fill="#FF8205"
    />
    <path d="M15.5004 29H8.50043L8.50021 36H15.5004V29Z" fill="#FA500F" />
    <path d="M29.4998 29H22.5004V36H29.4998V29Z" fill="#FA500F" />
    <path
      d="M43.5004 29H36.5001L36.5004 36H43.5002L43.5004 29Z"
      fill="#FA500F"
    />
    <path d="M22.5004 36H15.5004H8.50021H1.5V43H22.5004V36Z" fill="#E10500" />
    <path d="M50.5 36H43.5002H36.5004H29.4998V43H50.5V36Z" fill="#E10500" />
  </svg>
);
export default SvgMistral;
