import { useEffect } from "react";
import { useState } from "react";

export const useNightTime = () => {
  const [isNight, setIsNight] = useState(false);

  useEffect(() => {
    const checkNightTime = () => {
      const currentHour = new Date().getHours();
      setIsNight(currentHour >= 18 || currentHour < 6);
    };

    checkNightTime();
    const interval = setInterval(checkNightTime, 60000); // Check every minute

    return () => clearInterval(interval);
  }, []);

  return { isNight };
};
