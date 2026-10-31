import SvgOnyxLogo from "@opal/logos/onyx-logo";
import SvgOnyxWordmark from "@opal/logos/onyx-wordmark";
import { cn } from "@opal/utils";

interface OnyxLogoWordmarkProps {
  size?: number;
  className?: string;
}

// # NOTE(@raunakab):
// This ratio is not some random, magical number; it is available on Figma.
const HEIGHT_TO_GAP_RATIO = 5 / 16;

const SvgOnyxLogoWordmark = ({
  size: height,
  className,
}: OnyxLogoWordmarkProps) => {
  const gap = height != null ? height * HEIGHT_TO_GAP_RATIO : undefined;

  return (
    <div
      className={cn(`flex flex-row items-center`, className)}
      style={{ gap }}
    >
      <SvgOnyxLogo size={height} />
      <SvgOnyxWordmark size={height} />
    </div>
  );
};
export default SvgOnyxLogoWordmark;
