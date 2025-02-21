export default function BlurBackground({
  visible,
  onClick,
}: {
  visible: boolean;
  onClick: () => void;
}) {
  return (
    <div
      onClick={onClick}
      className={`
        desktop:hidden w-full h-full fixed inset-0 bg-neutral-700 bg-opacity-50 backdrop-blur-sm z-30 transition-opacity duration-300 ease-in-out ${
          visible
            ? "opacity-100 pointer-events-auto"
            : "opacity-0 pointer-events-none"
        }`}
    />
  );
}
