import { FiToggleLeft, FiToggleRight } from "react-icons/fi";
import { useDemoModeContext } from "./DemoModeContext";

export function DemoModeToggle() {
  const { isDemoMode, toggleDemoMode } = useDemoModeContext();
  
  const handleToggle = () => {
    toggleDemoMode();
  };
  
  return (
    <div
      onClick={handleToggle}
      className="flex items-center gap-2 py-1.5 px-2 text-sm cursor-pointer rounded hover:bg-background-300"
    >
      {isDemoMode ? (
        <FiToggleRight className="h-4 w-4 text-green-500" />
      ) : (
        <FiToggleLeft className="h-4 w-4 text-gray-400" />
      )}
      <span className={isDemoMode ? "text-green-500" : ""}>
        Demo Mode {isDemoMode ? "On" : "Off"}
      </span>
    </div>
  );
} 