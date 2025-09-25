"use client";

import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  ReactNode,
} from "react";
import i18n from "@/i18n/init";

export type Language = "ru" | "en";

interface LanguageContextType {
  language: Language;
  changeLanguage: (lang: Language) => void;
  isLoading: boolean;
}

const LanguageContext = createContext<LanguageContextType | undefined>(
  undefined
);

interface LanguageProviderProps {
  children: ReactNode;
}

export function LanguageProvider({ children }: LanguageProviderProps) {
  const [language, setLanguage] = useState<Language>("ru");
  const [isLoading, setIsLoading] = useState(true);

  // Инициализация языка при загрузке
  useEffect(() => {
    const initializeLanguage = async () => {
      // Проверяем localStorage
      const savedLanguage = localStorage.getItem("language") as Language;

      if (savedLanguage && (savedLanguage === "ru" || savedLanguage === "en")) {
        setLanguage(savedLanguage);
        await i18n.changeLanguage(savedLanguage);
      } else {
        // Если нет сохраненного языка, используем браузерный или дефолтный 'ru'
        const browserLang = navigator.language.startsWith("en") ? "en" : "ru";
        setLanguage(browserLang);
        await i18n.changeLanguage(browserLang);
        localStorage.setItem("language", browserLang);
      }

      setIsLoading(false);
    };

    initializeLanguage();
  }, []);

  const changeLanguage = async (lang: Language) => {
    setLanguage(lang);
    await i18n.changeLanguage(lang);
    localStorage.setItem("language", lang);
  };

  const value: LanguageContextType = {
    language,
    changeLanguage,
    isLoading,
  };

  return (
    <LanguageContext.Provider value={value}>
      {children}
    </LanguageContext.Provider>
  );
}

export function useLanguage() {
  const context = useContext(LanguageContext);
  if (context === undefined) {
    throw new Error("useLanguage must be used within a LanguageProvider");
  }
  return context;
}
