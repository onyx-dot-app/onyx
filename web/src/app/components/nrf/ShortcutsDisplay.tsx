"use client";
import React from "react";
import { ShortCut, AddShortCut } from "@/components/extension/Shortcuts";
import { Shortcut } from "@/app/chat/nrf/interfaces";

interface ShortcutsDisplayProps {
  shortCuts: Shortcut[];
  showShortcuts: boolean;
  setEditingShortcut: (shortcut: Shortcut | null) => void;
  setShowShortCutModal: (show: boolean) => void;
  openShortCutModal: () => void;
}

export const ShortcutsDisplay: React.FC<ShortcutsDisplayProps> = ({
  shortCuts,
  showShortcuts,
  setEditingShortcut,
  setShowShortCutModal,
  openShortCutModal,
}) => {
  return (
    <div
      className={`
        mx-auto flex flex-wrap justify-center gap-x-6 gap-y-4 mt-12
        transition-all duration-700 ease-in-out
        ${
          showShortcuts
            ? "opacity-100 max-h-[500px]"
            : "opacity-0 max-h-0 overflow-hidden pointer-events-none"
        }
      `}
    >
      {shortCuts.map((shortCut: Shortcut, index: number) => (
        <ShortCut
          key={index}
          onEdit={() => {
            setEditingShortcut(shortCut);
            setShowShortCutModal(true);
          }}
          shortCut={shortCut}
        />
      ))}
      <AddShortCut openShortCutModal={openShortCutModal} />
    </div>
  );
};
