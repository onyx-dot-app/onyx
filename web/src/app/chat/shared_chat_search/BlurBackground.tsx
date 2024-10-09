export default function BlurBackground({ visible }: { visible: boolean }) {
  return (
    <div
      className={`desktop:hidden w-full h-full fixed inset-0 bg-black bg-opacity-50 backdrop-blur-sm z-30 transition-opacity duration-300 ease-in-out ${visible ? "opacity-100 pointer-events-auto" : "opacity-0 pointer-events-none"}`}
    />
  );
}
