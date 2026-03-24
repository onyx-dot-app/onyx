import SvgOnyxLogo from "@opal/icons/onyx-logo";
import SvgOnyxTyped from "@opal/icons/onyx-typed";
import { cn } from "@opal/utils";

interface OnyxLogoTypedProps {
  size?: number;
  className?: string;
}

const SvgOnyxLogoTyped = ({ size: height, className }: OnyxLogoTypedProps) => {
  // # NOTE(@raunakab):
  // This ratio is not some random, magical number; it is available on Figma.
const HEIGHT_TO_GAP_RATIO = 5 / 16;

const SvgOnyxLogoTyped = ({ size: height, className }: OnyxLogoTypedProps) => {
  const gap = height != null ? height * HEIGHT_TO_GAP_RATIO : undefined;

  return (
    <div
      className={cn(`flex flex-row items-center`, className)}
      style={{ gap }}
    >
      <SvgOnyxLogo size={height} />
      <SvgOnyxTyped size={height} />
    </div>
  );
};
export default SvgOnyxLogoTyped;
