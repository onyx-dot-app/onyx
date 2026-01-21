export default function VideoBackground() {
  return (
    <video
      autoPlay
      loop
      muted
      playsInline
      className="absolute inset-0 w-full h-full object-cover z-0 pointer-events-none opacity-30 blur-sm"
    >
      <source
        src="https://cdn.onyx.app/build/background.mp4"
        type="video/mp4"
      />
    </video>
  );
}
