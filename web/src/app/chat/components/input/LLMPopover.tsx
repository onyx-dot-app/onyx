import React, { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { getDisplayNameForModel, LlmDescriptor } from "@/lib/hooks";
import { structureValue } from "@/lib/llm/utils";
import { LLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import { getProviderIcon, getProviderType } from "@/app/admin/configuration/llm/utils";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { LlmManager } from "@/lib/hooks";
import { cn } from "@/lib/utils";

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { FiAlertTriangle, FiSearch, FiStar, FiX, FiBarChart2, FiClock } from "react-icons/fi";
import { BiBrain } from "react-icons/bi";
import { MdImage } from "react-icons/md";
import { ChatInputOption } from "./ChatInputOption";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";

interface LLMPopoverProps {
  llmProviders: LLMProviderDescriptor[];
  llmManager: LlmManager;
  requiresImageGeneration?: boolean;
  currentAssistant?: MinimalPersonaSnapshot;
  trigger?: React.ReactElement;
  onSelect?: (value: string) => void;
  currentModelName?: string;
  align?: "start" | "center" | "end";
}

export default function LLMPopover({
  llmProviders,
  llmManager,
  requiresImageGeneration,
  currentAssistant,
  trigger,
  onSelect,
  currentModelName,
  align,
}: LLMPopoverProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [expandedGroup, setExpandedGroup] = useState<string>("");
  const [hoverTimer, setHoverTimer] = useState<NodeJS.Timeout | null>(null);
  const [search, setSearch] = useState("");
  const [favorites, setFavorites] = useState<string[]>([]);
  const [recent, setRecent] = useState<string[]>([]);
  const listboxRef = useRef<HTMLDivElement | null>(null);
  const optionRefs = useRef<HTMLButtonElement[]>([]);
  const [focusIndex, setFocusIndex] = useState(0);

  const FAVORITES_KEY = "llm_popover_favorites_v1";
  const RECENT_KEY = "llm_popover_recent_v1";

  useEffect(() => {
    if (isOpen) {
      const currentModel = currentModelName || llmManager.currentLlm.modelName;
      if (currentModel) {
        for (const llmProvider of llmProviders) {
          const hasCurrentModel = llmProvider.model_configurations.some(
            (config) => config.name === currentModel
          );
          if (hasCurrentModel) {
            const { type: providerType } = getProviderTypeAndName(
              llmProvider.provider,
              currentModel
            );
            setExpandedGroup(providerType);
            break;
          }
        }
      }
    } else {
      if (hoverTimer) {
        clearTimeout(hoverTimer);
        setHoverTimer(null);
      }
    }
  }, [isOpen, currentModelName, llmManager.currentLlm.modelName, llmProviders]);

  useEffect(() => {
    return () => {
      if (hoverTimer) clearTimeout(hoverTimer);
    };
  }, [hoverTimer]);

  useEffect(() => {
    try {
      const fav = JSON.parse(localStorage.getItem(FAVORITES_KEY) || "[]");
      const rec = JSON.parse(localStorage.getItem(RECENT_KEY) || "[]");
      if (Array.isArray(fav)) setFavorites(fav);
      if (Array.isArray(rec)) setRecent(rec);
    } catch {}
  }, []);

  useEffect(() => {
    try { localStorage.setItem(FAVORITES_KEY, JSON.stringify(favorites)); } catch {}
  }, [favorites]);
  useEffect(() => {
    try { localStorage.setItem(RECENT_KEY, JSON.stringify(recent.slice(0, 7))); } catch {}
  }, [recent]);

  const triggerContent = useMemo(
    trigger
      ? () => trigger
      : () => (
          <button className="dark:text-[#fff] text-[#000] focus:outline-none" data-testid="llm-popover-trigger">
            <ChatInputOption
              minimize
              toggle
              flexPriority="stiff"
              name={getDisplayNameForModel(llmManager.currentLlm.modelName)}
              Icon={getProviderIcon(
                llmManager.currentLlm.provider,
                llmManager.currentLlm.modelName
              )}
              tooltipContent="Switch models"
            />
          </button>
        ),
    [llmManager.currentLlm]
  );

  const getProviderTypeAndName = (providerName: string, modelName: string) => {
    const providerType = getProviderType(providerName, modelName);
    const displayNames: Record<string, string> = {
      anthropic: "Anthropic",
      amazon: "Amazon",
      microsoft: "Microsoft",
      mistral: "Mistral",
      meta: "Meta",
      google: "Google",
      deepseek: "DeepSeek",
      openai: "OpenAI",
      xai: "xAI",
      qwen: "Qwen",
      cohere: "Cohere",
      other: "Other",
    };
    return { type: providerType, displayName: displayNames[providerType] || "Other" };
  };

  type FlatModel = {
    value: string;
    name: string;
    provider: string;
    modelName: string;
    providerType: string;
    displayName: string;
    maxTokens?: number | null;
    supportsVision: boolean;
    supportsReasoning: boolean;
  };

  const groupedModels = useMemo(() => {
    const groups = new Map<string, {
      providerType: string;
      displayName: string;
      icon: any;
      models: Array<{
        name: string;
        provider: string;
        modelName: string;
        maxTokens?: number | null;
        supportsVision: boolean;
        supportsReasoning: boolean;
      }>;
    }>();

    llmProviders.forEach((llmProvider) => {
      const visibleModels = llmProvider.model_configurations.filter(
        (modelConfiguration) => modelConfiguration.is_visible || modelConfiguration.name === currentModelName
      );
      visibleModels.forEach((modelConfiguration) => {
        const { type: providerType, displayName } = getProviderTypeAndName(
          llmProvider.provider,
          modelConfiguration.name
        );
        const providerIcon = getProviderIcon(
          llmProvider.provider,
          modelConfiguration.name
        );
        if (!groups.has(providerType)) {
          groups.set(providerType, { providerType, displayName, icon: providerIcon, models: [] });
        }
        const group = groups.get(providerType)!;
        group.models.push({
          name: llmProvider.name,
          provider: llmProvider.provider,
          modelName: modelConfiguration.name,
          maxTokens: modelConfiguration.max_input_tokens ?? null,
          supportsVision: modelConfiguration.supports_image_input,
          supportsReasoning: modelConfiguration.supports_reasoning,
        });
      });
    });

    const arr = Array.from(groups.values());
    arr.sort((a, b) => a.displayName.localeCompare(b.displayName));
    return arr;
  }, [llmProviders, currentModelName]);

  const allModelsFlat: FlatModel[] = useMemo(() => {
    const flat: FlatModel[] = [];
    groupedModels.forEach((group) => {
      group.models.forEach((m) => {
        const { providerType, displayName } = group;
        const value = structureValue(m.name, m.provider, m.modelName);
        flat.push({
          value,
          name: m.name,
          provider: m.provider,
          modelName: m.modelName,
          providerType,
          displayName,
          maxTokens: m.maxTokens,
          supportsVision: m.supportsVision,
          supportsReasoning: m.supportsReasoning,
        });
      });
    });
    return flat;
  }, [groupedModels]);

  const filteredGrouped = useMemo(() => {
    const matcher = (s: string) => s.toLowerCase().includes(search.toLowerCase());
    return groupedModels
      .map((group) => ({
        ...group,
        models: group.models.filter((m) => {
          if (search && !matcher(m.modelName) && !matcher(getDisplayNameForModel(m.modelName))) return false;
          return true;
        }),
      }))
      .filter((g) => g.models.length > 0);
  }, [groupedModels, search]);

  const favoriteModels = useMemo(() => {
    const matcher = (s: string) => s.toLowerCase().includes(search.toLowerCase());
    return favorites
      .map((val) => allModelsFlat.find((m) => m.value === val))
      .filter((m): m is FlatModel => Boolean(m))
      .filter((m) => {
        if (search && !matcher(m.modelName) && !matcher(getDisplayNameForModel(m.modelName))) return false;
        return true;
      });
  }, [favorites, allModelsFlat, search]);

  const recentModels = useMemo(() => {
    const matcher = (s: string) => s.toLowerCase().includes(search.toLowerCase());
    const favSet = new Set(favorites);
    return recent
      .filter((val) => !favSet.has(val))
      .map((val) => allModelsFlat.find((m) => m.value === val))
      .filter((m): m is FlatModel => Boolean(m))
      .filter((m) => {
        if (search && !matcher(m.modelName) && !matcher(getDisplayNameForModel(m.modelName))) return false;
        return true;
      });
  }, [recent, favorites, allModelsFlat, search]);

  const visibleOptions = useMemo(() => {
    const arr: { value: string }[] = [];
    favoriteModels.forEach((m) => arr.push({ value: m.value }));
    recentModels.forEach((m) => arr.push({ value: m.value }));
    filteredGrouped.forEach((g) => g.models.forEach((m) => arr.push({ value: structureValue(m.name, m.provider, m.modelName) })));
    return arr;
  }, [favoriteModels, recentModels, filteredGrouped]);

  const firstHighlightValue = visibleOptions[0]?.value;

  const isFavorited = useCallback((value: string) => favorites.includes(value), [favorites]);
  const toggleFavorite = useCallback((value: string) => {
    setFavorites((prev) => (prev.includes(value) ? prev.filter((v) => v !== value) : [value, ...prev]));
  }, []);
  const pushRecent = useCallback((value: string) => {
    setRecent((prev) => [value, ...prev.filter((v) => v !== value)].slice(0, 7));
  }, []);

  const getFirstSelectable = useCallback(() => {
    const pickFromFlat = (arr: FlatModel[]) => {
      for (const m of arr) {
        if (!requiresImageGeneration || m.supportsVision) {
          return { name: m.name, provider: m.provider, modelName: m.modelName, value: m.value } as const;
        }
      }
      return null;
    };
    const fav = pickFromFlat(favoriteModels);
    if (fav) return fav;
    const rec = pickFromFlat(recentModels);
    if (rec) return rec;
    for (const g of filteredGrouped) {
      for (const m of g.models) {
        if (!requiresImageGeneration || m.supportsVision) {
          return { name: m.name, provider: m.provider, modelName: m.modelName, value: structureValue(m.name, m.provider, m.modelName) } as const;
        }
      }
    }
    return null;
  }, [favoriteModels, recentModels, filteredGrouped, requiresImageGeneration]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLDivElement>) => {
    const options = optionRefs.current;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setFocusIndex((prev) => Math.min(prev + 1, options.length - 1));
      options[Math.min(focusIndex + 1, options.length - 1)]?.focus();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setFocusIndex((prev) => Math.max(prev - 1, 0));
      options[Math.max(focusIndex - 1, 0)]?.focus();
    } else if (e.key === "Enter") {
      e.preventDefault();
      options[focusIndex]?.click();
    }
  }, [focusIndex]);

  const selectFirstResult = useCallback(() => {
    const pick = getFirstSelectable();
    if (!pick) return;
    llmManager.updateCurrentLlm({ name: pick.name, provider: pick.provider, modelName: pick.modelName } as LlmDescriptor);
    setIsOpen(false);
    onSelect?.(pick.value);
    pushRecent(pick.value);
  }, [getFirstSelectable, llmManager, onSelect, pushRecent]);

  useEffect(() => {
    const handler = (e: any) => {
      const src = e?.detail?.source;
      if (src && src !== "llm") setIsOpen(false);
    };
    window.addEventListener("onyx-chat-input-popover-open", handler as EventListener);
    return () => window.removeEventListener("onyx-chat-input-popover-open", handler as EventListener);
  }, []);

  return (
    <Popover
      open={isOpen}
      onOpenChange={(open) => {
        setIsOpen(open);
        if (open) {
          try {
            window.dispatchEvent(new CustomEvent("onyx-chat-input-popover-open", { detail: { source: "llm" } }));
          } catch {}
        }
      }}
    >
      <PopoverTrigger asChild>{triggerContent}</PopoverTrigger>
      <PopoverContent align={align || "start"} className="min-w-[180px] max-w-[280px] w-[min(280px,calc(100vw-48px))] p-0 bg-background border border-gray-200 dark:border-gray-700 rounded-md shadow-lg flex flex-col">
        <div className="p-2 border-b border-gray-200 dark:border-gray-700 space-y-2">
          <div className="relative">
            <FiSearch className="absolute left-2 top-1/2 -translate-y-1/2 text-gray-400" size={14} />
            <input
              autoFocus
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  selectFirstResult();
                }
              }}
              placeholder="Search models"
              className="w-full pl-7 pr-6 py-1.5 text-sm rounded-md bg-background outline-none border border-gray-200 dark:border-gray-700"
            />
            {search && (
              <button className="absolute right-1.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600" onClick={() => setSearch("")} aria-label="Clear search">
                <FiX size={14} />
              </button>
            )}
          </div>
        </div>
        <div className="flex-grow max-h-[calc(100vh-220px)] overflow-y-auto rounded-md" onKeyDown={handleKeyDown} ref={listboxRef} role="listbox" aria-label="Models">
          <Accordion type="single" value={expandedGroup} onValueChange={(value) => setExpandedGroup(value || "")} collapsible className="w-full">
            {favoriteModels.length > 0 && (
              <AccordionItem key="favorites" value="favorites" className="border-b border-gray-200 dark:border-gray-700">
                <AccordionTrigger className="hover:bg-gray-50 dark:hover:bg-gray-800 px-3 py-2"
                  onMouseEnter={() => { if (hoverTimer) clearTimeout(hoverTimer); const t = setTimeout(() => setExpandedGroup("favorites"), 250); setHoverTimer(t); }}
                  onMouseLeave={() => { if (hoverTimer) { clearTimeout(hoverTimer); setHoverTimer(null); } }}
                >
                  <div className="flex items-center gap-2">
                    <FiStar className="w-4 h-4 text-yellow-500" />
                    <span className="text-sm font-medium">Favorites</span>
                    <span className="text-xs text-gray-500 dark:text-gray-400">({favoriteModels.length})</span>
                  </div>
                </AccordionTrigger>
                <AccordionContent noPadding className="p-0 bg-gray-100 dark:bg-gray-800">
                  {favoriteModels.map((fm) => {
                    const isSelected = fm.modelName === llmManager.currentLlm.modelName;
                    const canSelect = !requiresImageGeneration || fm.supportsVision;
                    const value = fm.value;
                    return (
                      <button
                        key={value}
                        onClick={() => {
                          if (!canSelect) return;
                          llmManager.updateCurrentLlm({ name: fm.name, provider: fm.provider, modelName: fm.modelName } as LlmDescriptor);
                          setIsOpen(false);
                          onSelect?.(value);
                          pushRecent(value);
                        }}
                        disabled={!canSelect}
                        className={cn(
                          "w-full text-left px-3 py-2 text-sm transition-colors flex items-start gap-2 group",
                          isSelected ? "bg-primary/10 text-primary font-medium" : canSelect ? cn("hover:bg-background-chat-hover", firstHighlightValue === value && "bg-background-chat-hover") : "text-gray-400 dark:text-gray-600 cursor-not-allowed"
                        )}
                        role="option"
                        aria-selected={isSelected}
                        ref={(el) => { if (el) optionRefs.current.push(el!); }}
                      >
                        <div className="flex items-center gap-2 min-w-0 flex-1">
                          <span className={cn("rounded-full flex-shrink-0 transition-all", isSelected ? "w-2 h-2 bg-primary ring-2 ring-primary/40" : "w-1.5 h-1.5 bg-gray-300 dark:bg-gray-600 group-hover:bg-neutral-500 dark:group-hover:bg-neutral-400")} />
                          <div className="min-w-0">
                            <div className="truncate" title={fm.modelName}>{getDisplayNameForModel(fm.modelName)}</div>
                          </div>
                        </div>
                        <div className="flex items-center gap-1 flex-shrink-0 ml-2">
                          {fm.maxTokens ? (<FiBarChart2 className="w-3.5 h-3.5 text-gray-500 dark:text-gray-400" title={`Context: ${fm.maxTokens.toLocaleString()} tokens`} />) : null}
                          {fm.supportsReasoning && (<BiBrain className="w-3.5 h-3.5 text-gray-500 dark:text-gray-400" title="Supports reasoning" />)}
                          {fm.supportsVision && (<MdImage className="w-3.5 h-3.5 text-gray-500 dark:text-gray-400" title="Supports image input" />)}
                          {!canSelect && requiresImageGeneration && (<FiAlertTriangle className="w-3 h-3 text-yellow-500" />)}
                          <button type="button" className="ml-1 text-gray-400 hover:text-gray-600" onClick={(e) => { e.stopPropagation(); toggleFavorite(value); }} aria-label={isFavorited(value) ? "Unfavorite" : "Favorite"} title={isFavorited(value) ? "Unfavorite" : "Favorite"}>
                            <FiStar className={cn("w-3.5 h-3.5", isFavorited(value) ? "text-yellow-500" : "")} />
                          </button>
                        </div>
                      </button>
                    );
                  })}
                </AccordionContent>
              </AccordionItem>
            )}
            {recentModels.length > 0 && (
              <AccordionItem key="recent" value="recent" className="border-b border-gray-200 dark:border-gray-700">
                <AccordionTrigger
                  className="hover:bg-gray-50 dark:hover:bg-gray-800 px-3 py-2"
                  onMouseEnter={() => { if (hoverTimer) clearTimeout(hoverTimer); const t = setTimeout(() => setExpandedGroup("recent"), 250); setHoverTimer(t); }}
                  onMouseLeave={() => { if (hoverTimer) { clearTimeout(hoverTimer); setHoverTimer(null); } }}
                >
                  <div className="flex items-center gap-2">
                    <FiClock className="w-4 h-4 text-gray-500 dark:text-gray-400" />
                    <span className="text-sm font-medium">Recent</span>
                    <span className="text-xs text-gray-500 dark:text-gray-400">({recentModels.length})</span>
                  </div>
                </AccordionTrigger>
                <AccordionContent noPadding className="p-0 bg-gray-100 dark:bg-gray-800">
                  {recentModels.map((rm) => {
                    const isSelected = rm.modelName === llmManager.currentLlm.modelName;
                    const canSelect = !requiresImageGeneration || rm.supportsVision;
                    const value = rm.value;
                    return (
                      <button
                        key={value}
                        onClick={() => {
                          if (!canSelect) return;
                          llmManager.updateCurrentLlm({ name: rm.name, provider: rm.provider, modelName: rm.modelName } as LlmDescriptor);
                          setIsOpen(false);
                          onSelect?.(value);
                          pushRecent(value);
                        }}
                        disabled={!canSelect}
                        className={cn(
                          "w-full text-left px-3 py-2 text-sm transition-colors flex items-start gap-2 group",
                          isSelected ? "bg-primary/10 text-primary font-medium" : canSelect ? cn("hover:bg-background-chat-hover", firstHighlightValue === value && "bg-background-chat-hover") : "text-gray-400 dark:text-gray-600 cursor-not-allowed"
                        )}
                        role="option"
                        aria-selected={isSelected}
                        ref={(el) => { if (el) optionRefs.current.push(el!); }}
                      >
                        <div className="flex items-center gap-2 min-w-0 flex-1">
                          <span className={cn("rounded-full flex-shrink-0 transition-all", isSelected ? "w-2 h-2 bg-primary ring-2 ring-primary/40" : "w-1.5 h-1.5 bg-gray-300 dark:bg-gray-600 group-hover:bg-neutral-500 dark:group-hover:bg-neutral-400")} />
                          <div className="min-w-0">
                            <div className="truncate" title={rm.modelName}>{getDisplayNameForModel(rm.modelName)}</div>
                          </div>
                        </div>
                        <div className="flex items-center gap-1 flex-shrink-0 ml-2">
                          {rm.maxTokens ? (<FiBarChart2 className="w-3.5 h-3.5 text-gray-500 dark:text-gray-400" title={`Context: ${rm.maxTokens.toLocaleString()} tokens`} />) : null}
                          {rm.supportsReasoning && (<BiBrain className="w-3.5 h-3.5 text-gray-500 dark:text-gray-400" title="Supports reasoning" />)}
                          {rm.supportsVision && (<MdImage className="w-3.5 h-3.5 text-gray-500 dark:text-gray-400" title="Supports image input" />)}
                          {!canSelect && requiresImageGeneration && (<FiAlertTriangle className="w-3 h-3 text-yellow-500" />)}
                        </div>
                      </button>
                    );
                  })}
                </AccordionContent>
              </AccordionItem>
            )}
            {filteredGrouped.map((group) => (
              <AccordionItem key={group.providerType} value={group.providerType} className="border-b border-gray-200 dark:border-gray-700 last:border-b-0">
                <AccordionTrigger className="hover:bg-gray-50 dark:hover:bg-gray-800 px-3 py-2"
                  onMouseEnter={() => { if (hoverTimer) clearTimeout(hoverTimer); const t = setTimeout(() => setExpandedGroup(group.providerType), 250); setHoverTimer(t); }}
                  onMouseLeave={() => { if (hoverTimer) { clearTimeout(hoverTimer); setHoverTimer(null); } }}
                >
                  <div className="flex items-center gap-2">
                    <span className="w-4 h-4">{group.icon({ size: 16 })}</span>
                    <span className="text-sm font-medium">{group.displayName}</span>
                  </div>
                </AccordionTrigger>
                <AccordionContent noPadding className="p-0 bg-gray-100 dark:bg-gray-800">
                  {group.models.map((model) => {
                    const supportsVision = model.supportsVision;
                    const supportsReasoning = model.supportsReasoning;
                    const canSelect = !requiresImageGeneration || supportsVision;
                    const value = structureValue(model.name, model.provider, model.modelName);
                    const isSelected = model.modelName === llmManager.currentLlm.modelName;
                    return (
                      <TooltipProvider key={value}>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <button
                              onClick={() => {
                                if (!canSelect) return;
                                llmManager.updateCurrentLlm({
                                  name: model.name,
                                  provider: model.provider,
                                  modelName: model.modelName,
                                } as LlmDescriptor);
                                setIsOpen(false);
                                onSelect?.(value);
                                pushRecent(value);
                              }}
                              disabled={!canSelect}
                              className={cn(
                                "w-full text-left px-3 py-2 text-sm transition-colors flex items-start gap-2 group",
                                isSelected ? "bg-primary/10 text-primary font-medium" : canSelect ? cn("hover:bg-background-chat-hover", firstHighlightValue === value && "bg-background-chat-hover") : "text-gray-400 dark:text-gray-600 cursor-not-allowed"
                              )}
                              role="option"
                              aria-selected={isSelected}
                              ref={(el) => { if (el) optionRefs.current.push(el!); }}
                            >
                              <div className="flex items-center gap-2 min-w-0 flex-1">
                                <span className={cn("rounded-full flex-shrink-0 transition-all", isSelected ? "w-2 h-2 bg-primary ring-2 ring-primary/40" : "w-1.5 h-1.5 bg-gray-300 dark:bg-gray-600 group-hover:bg-neutral-500 dark:group-hover:bg-neutral-400")} />
                                <div className="min-w-0">
                                  <div className="truncate" title={model.modelName}>{getDisplayNameForModel(model.modelName)}</div>
                                </div>
                              </div>
                              <div className="flex items-center gap-1 flex-shrink-0 ml-2">
                                {model.maxTokens ? (<FiBarChart2 className="w-3.5 h-3.5 text-gray-500 dark:text-gray-400" title={`Context: ${model.maxTokens.toLocaleString()} tokens`} />) : null}
                                {supportsReasoning && (<BiBrain className="w-3.5 h-3.5 text-gray-500 dark:text-gray-400" title="Supports reasoning" />)}
                                {supportsVision && (<MdImage className="w-3.5 h-3.5 text-gray-500 dark:text-gray-400" title="Supports image input" />)}
                                {!canSelect && requiresImageGeneration && (<FiAlertTriangle className="w-3 h-3 text-yellow-500" />)}
                                <button type="button" className="ml-1 text-gray-400 hover:text-gray-600" onClick={(e) => { e.stopPropagation(); toggleFavorite(value); }} aria-label={isFavorited(value) ? "Unfavorite" : "Favorite"} title={isFavorited(value) ? "Unfavorite" : "Favorite"}>
                                  <FiStar className={cn("w-3.5 h-3.5", isFavorited(value) ? "text-yellow-500" : "")} />
                                </button>
                              </div>
                            </button>
                          </TooltipTrigger>
                          {!canSelect && (
                            <TooltipContent>
                              <p>This model doesn't support image inputs</p>
                            </TooltipContent>
                          )}
                        </Tooltip>
                      </TooltipProvider>
                    );
                  })}
                </AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
          {filteredGrouped.length === 0 && (
            <div className="p-4 text-sm text-gray-500">
              <div>No models match your filters.</div>
              <button className="mt-2 text-primary hover:underline" onClick={() => { setSearch(""); }}>
                Reset filters
              </button>
            </div>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}

