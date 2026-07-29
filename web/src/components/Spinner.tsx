import "./spinner.css";

export const Spinner = () => {
  return (
    <div className="fixed inset-0 z-modal flex items-center justify-center bg-mask-03 backdrop-blur-03">
      <div className="loader ease-linear rounded-full border-8 border-t-8 border-background-200 h-8 w-8"></div>
    </div>
  );
};
