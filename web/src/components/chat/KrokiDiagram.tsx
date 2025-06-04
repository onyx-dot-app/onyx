"use client";

import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import {
  AlertTriangle, Loader2, Download, Copy, Maximize2, Code as CodeIcon, ClipboardCopy,
  ZoomIn, ZoomOut, ArrowUp, ArrowDown, ArrowLeft, ArrowRight, RefreshCcw
} from 'lucide-react';
import { Button } from "@/components/ui/button";
import { CodeBlock } from "@/app/chat/message/CodeBlock";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogClose,
} from "@/components/ui/dialog";
import { KROKI_SUPPORTED_LANGUAGES } from "@/lib/kroki_constants";

interface KrokiDiagramProps {
  diagramType: string;
  codeText: string;
  onFeatureDisabled: () => void;
  isStreaming?: boolean;
  isCodeComplete?: boolean;
}

enum LoadingPhase {
  RETRIEVING = "retrieving",
  PARSING = "parsing",
  RENDERING = "rendering"
}

const KrokiDiagram: React.FC<KrokiDiagramProps> = ({
  diagramType,
  codeText,
  onFeatureDisabled,
  isStreaming = false,
  isCodeComplete = true
}) => {
  const [svgContent, setSvgContent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [renderFallbackAsCodeBlock, setRenderFallbackAsCodeBlock] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [loadingPhase, setLoadingPhase] = useState<LoadingPhase>(LoadingPhase.RETRIEVING);
  const [inRetrievingPhase, setInRetrievingPhase] = useState(false);
  const retrievingConfiguredRef = useRef(false); // Correct ref name
  const [showRawCode, setShowRawCode] = useState(false);
  const [showFullscreenModal, setShowFullscreenModal] = useState(false);
  const [copyStatus, setCopyStatus] = useState<string | null>(null);
  const [copyCodeStatus, setCopyCodeStatus] = useState<string | null>(null);
  const [currentAppTheme, setCurrentAppTheme] = useState<'light' | 'dark'>(() => {
    if (typeof window !== 'undefined') {
      return document.documentElement.classList.contains('dark') ? 'dark' : 'light';
    }
    return 'light';
  });

  const [fullscreenScale, setFullscreenScale] = useState(1);
  const [fullscreenTranslateX, setFullscreenTranslateX] = useState(0);
  const [fullscreenTranslateY, setFullscreenTranslateY] = useState(0);
  const PAN_STEP = 50;
  const ZOOM_FACTOR = 1.2;

  const onFeatureDisabledRef = useRef(onFeatureDisabled);
  useEffect(() => {
    onFeatureDisabledRef.current = onFeatureDisabled;
  }, [onFeatureDisabled]);

  useEffect(() => {
    setCurrentAppTheme(document.documentElement.classList.contains('dark') ? 'dark' : 'light');
    if (typeof window === 'undefined') return;
    const observer = new MutationObserver((mutationsList) => {
      for (const mutation of mutationsList) {
        if (mutation.type === 'attributes' && mutation.attributeName === 'class') {
          const newTheme = document.documentElement.classList.contains('dark') ? 'dark' : 'light';
          setCurrentAppTheme(newTheme);
        }
      }
    });
    observer.observe(document.documentElement, { attributes: true });
    return () => {
      observer.disconnect();
    };
  }, []);

  useEffect(() => {
    if (showFullscreenModal) {
      setFullscreenScale(1);
      setFullscreenTranslateX(0);
      setFullscreenTranslateY(0);
    }
  }, [showFullscreenModal]);

  const handleFullscreenZoomIn = () => setFullscreenScale(prev => prev * ZOOM_FACTOR);
  const handleFullscreenZoomOut = () => setFullscreenScale(prev => prev / ZOOM_FACTOR);
  const handleFullscreenPan = (dx: number, dy: number) => {
    setFullscreenTranslateX(prev => prev + dx);
    setFullscreenTranslateY(prev => prev + dy);
  };
  const handleFullscreenResetView = () => {
    setFullscreenScale(1);
    setFullscreenTranslateX(0);
    setFullscreenTranslateY(0);
  };

  const handleDownloadSvg = useCallback(() => {
    if (!svgContent) return;
    const blob = new Blob([svgContent], { type: 'image/svg+xml' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${diagramType}-diagram.svg`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, [svgContent, diagramType]);

  const handleToggleRawCode = () => {
    setShowRawCode(prev => !prev);
  };

  const handleCopyAsImage = useCallback(async () => {
    if (!svgContent) return;
    setCopyStatus("Copying...");
    try {
      const cleanedSvgContent = svgContent.replace(/<foreignObject[\s\S]*?<\/foreignObject>/g, '');
      const img = new Image();
      img.crossOrigin = "anonymous";
      const svgBlob = new Blob([cleanedSvgContent], { type: 'image/svg+xml;charset=utf-8' });
      const url = URL.createObjectURL(svgBlob);
      img.onload = async () => {
        const canvas = document.createElement('canvas');
        const scale = window.devicePixelRatio || 1;
        canvas.width = img.width * scale;
        canvas.height = img.height * scale;
        const ctx = canvas.getContext('2d');
        if (!ctx) {
          throw new Error('Could not get canvas context');
        }
        ctx.scale(scale, scale);
        ctx.drawImage(img, 0, 0);
        canvas.toBlob(async (blob) => {
          if (!blob) {
            throw new Error('Canvas to Blob conversion failed');
          }
          try {
            await navigator.clipboard.write([
              new ClipboardItem({ 'image/png': blob })
            ]);
            setCopyStatus("Copied!");
          } catch (clipErr) {
            console.error('Clipboard API error:', clipErr);
            setCopyStatus("Copy failed.");
          } finally {
            URL.revokeObjectURL(url);
            setTimeout(() => setCopyStatus(null), 2000);
          }
        }, 'image/png');
      };
      img.onerror = () => {
        URL.revokeObjectURL(url);
        throw new Error('Image loading failed');
      };
      img.src = url;
    } catch (err) {
      console.error("Error copying SVG as image:", err);
      setCopyStatus(err instanceof Error ? err.message : "Error.");
      setTimeout(() => setCopyStatus(null), 2000);
    }
  }, [svgContent]);

  const handleCopyCode = useCallback(() => {
    if (!codeText) return;
    setCopyCodeStatus("Copying...");
    navigator.clipboard.writeText(codeText)
      .then(() => {
        setCopyCodeStatus("Copied!");
        setTimeout(() => setCopyCodeStatus(null), 2000);
      })
      .catch(err => {
        console.error("Failed to copy code: ", err);
        setCopyCodeStatus("Failed!");
        setTimeout(() => setCopyCodeStatus(null), 2000);
      });
  }, [codeText]);

  // Effect to manage the "Retrieving" phase UI and state
  useEffect(() => {
    if (isStreaming && !isCodeComplete) {
      // Condition: Actively streaming and code is not yet complete.
      if (!retrievingConfiguredRef.current) {
        // This is the first time we hit this condition for the current diagram attempt.
        // Configure the "Retrieving" state.
        setIsLoading(true);
        setLoadingPhase(LoadingPhase.RETRIEVING);
        setInRetrievingPhase(true); // Gate for the main processing effect
        setError(null);
        setSvgContent(null);
        setRenderFallbackAsCodeBlock(false);
        retrievingConfiguredRef.current = true; // Mark as configured.
      } else {
        // Already configured, stream is ongoing, code still incomplete.
        // Ensure we stay in the "inRetrievingPhase" state if it somehow got unset.
        if (!inRetrievingPhase) {
          setInRetrievingPhase(true);
        }
      }
    } else {
      // Condition: Not (actively streaming AND code incomplete).
      // This means either:
      //   1. Streaming stopped (`!isStreaming`).
      //   2. Code is complete (`isCodeComplete`).
      //   3. Both.

      // We must exit the "inRetrievingPhase" state to allow main processing or final state.
      if (inRetrievingPhase) {
        setInRetrievingPhase(false);
      }

      // Reset retrievingConfiguredRef only when isCodeComplete becomes true.
      // This makes the "setLoadingPhase(LoadingPhase.RETRIEVING)" truly once per incomplete diagram lifecycle,
      // resilient to isStreaming prop flapping.
      if (isCodeComplete && retrievingConfiguredRef.current) {
        retrievingConfiguredRef.current = false;
      }
    }
  }, [isStreaming, isCodeComplete, inRetrievingPhase]); // inRetrievingPhase is read and set

  const getLoadingMessage = useCallback(() => {
    switch (loadingPhase) {
      case LoadingPhase.RETRIEVING:
        return "Retrieving chart...";
      case LoadingPhase.PARSING:
        return "Parsing chart...";
      case LoadingPhase.RENDERING:
        return "Loading diagram...";
      default:
        return "Loading diagram...";
    }
  }, [loadingPhase]);

  const loadingIndicator = useMemo(() => {
    return (
      <div className="kroki-diagram-outer-container relative group overflow-hidden flex flex-col" style={{
        borderRadius: '0.5rem',
        border: currentAppTheme === 'dark' ? '1px solid #374151' : '1px solid #e5e7eb',
        boxShadow: 'none',
        outline: 'none',
        background: 'transparent'
      }}>
        <style>{`
          .prose pre:has(.kroki-diagram-outer-container) {
            background: transparent !important;
            border: none !important;
            border-radius: 0 !important;
            padding: 0 !important;
            margin: 0 !important;
            box-shadow: none !important;
            outline: none !important;
          }
        `}</style>
        <div className="kroki-diagram-inner-container p-4 grow flex flex-col items-center justify-center min-h-[200px]" style={{
          backgroundColor: currentAppTheme === 'dark' ? '#1f2937' : '#ffffff',
          borderRadius: '0.5rem',
          border: 'none',
          boxShadow: 'none',
          outline: 'none'
        }}>
          <Loader2 className="h-10 w-10 animate-spin text-gray-500 dark:text-gray-400 mb-3" />
          <p className="text-sm text-gray-600 dark:text-gray-300">{getLoadingMessage()}</p>
        </div>
      </div>
    );
  }, [currentAppTheme, getLoadingMessage]);

  useEffect(() => {
    if (!KROKI_SUPPORTED_LANGUAGES.has(diagramType)) {
      setError(`Unsupported diagram type: ${diagramType}`);
      setIsLoading(false);
      return;
    }

    if (inRetrievingPhase) { // Gate: Don't process if we are in the "Retrieving" phase
      return;
    }

    const debounceTime = isCodeComplete ? 0 : 300;
    const handler = setTimeout(() => {
      if (codeText.trim() === "") {
        setError("Diagram code cannot be empty.");
        setSvgContent(null);
        setIsLoading(false);
        setRenderFallbackAsCodeBlock(false);
        return;
      }

      const fetchDiagram = async () => {
        setIsLoading(true);
        setLoadingPhase(LoadingPhase.PARSING); // Now we are parsing
        setError(null);
        setSvgContent(null);

        let processedCodeText = codeText;
        const isDarkMode = currentAppTheme === 'dark';

        if (diagramType === 'mermaid') {
          const mermaidTheme = isDarkMode ? 'dark' : 'default';
          processedCodeText = `%%{init: {'theme':'${mermaidTheme}'}}%%\n${codeText}`;
        } else if ((diagramType === 'plantuml' || diagramType === 'c4plantuml') && isDarkMode) {
          const plantUmlDarkTheme = 'skinparam backgroundColor #333333\nskinparam shadowing false\nskinparam FontColor #FFFFFF\nskinparam ArrowColor #CCCCCC\nskinparam ActorBorderColor #CCCCCC\nskinparam ParticipantBorderColor #CCCCCC\nskinparam NoteBorderColor #CCCCCC\nskinparam ClassBorderColor #CCCCCC\n';
          processedCodeText = `${plantUmlDarkTheme}${codeText}`;
        }

        try {
          const response = await fetch(`/api/kroki/${diagramType}`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({ content: processedCodeText }),
          });

          if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            const errorMessage = errorData.detail || errorData.error || `Failed to render diagram (status: ${response.status})`;
            if (response.status === 404 || (errorMessage && errorMessage.toLowerCase().includes("kroki service not enabled"))) {
              if (typeof onFeatureDisabledRef.current === 'function') {
                onFeatureDisabledRef.current();
              }
            }
            throw new Error(errorMessage);
          }

          setLoadingPhase(LoadingPhase.RENDERING);
          const result = await response.json();
          if (result.svg) {
            let rawSvg = result.svg;
            if (rawSvg.trim().startsWith("<?xml")) {
              try {
                const parser = new DOMParser();
                const xmlDoc = parser.parseFromString(rawSvg, "application/xml");
                const svgElement = xmlDoc.getElementsByTagName("svg")[0];
                if (svgElement) {
                  rawSvg = svgElement.outerHTML;
                } else {
                  throw new Error("SVG tag not found in XML-wrapped content.");
                }
              } catch (parseError) {
                console.error("Error parsing XML-wrapped SVG:", parseError);
                setError(parseError instanceof Error ? `SVG Parse Error: ${parseError.message}` : "SVG Parse Error");
                setRenderFallbackAsCodeBlock(true);
                setIsLoading(false);
                return;
              }
            }
            setSvgContent(rawSvg);
            setRenderFallbackAsCodeBlock(false);
          } else {
            const krokiErrorMsg = result.error ? `Kroki Error: ${result.error} (Type: ${result.error_type})` : 'Unexpected response from Kroki service.';
            console.warn(krokiErrorMsg);
            setError(krokiErrorMsg);
            setRenderFallbackAsCodeBlock(true);
          }
        } catch (err) {
          const fetchErrorMsg = err instanceof Error ? err.message : 'An unknown error occurred during fetch.';
          console.error("Error fetching Kroki diagram:", err);
          setError(fetchErrorMsg);
          setRenderFallbackAsCodeBlock(true);
        } finally {
          setIsLoading(false);
        }
      };
      fetchDiagram();
    }, debounceTime);

    return () => {
      clearTimeout(handler);
    };
  }, [diagramType, codeText, currentAppTheme, onFeatureDisabledRef, isStreaming, isCodeComplete, inRetrievingPhase]);

  if (isLoading) {
    return loadingIndicator;
  }

  if (renderFallbackAsCodeBlock) {
    return (
      <CodeBlock codeText={codeText} className={`language-${diagramType}`} isFallback={true}>
        {[codeText]}
      </CodeBlock>
    );
  }

  if (svgContent) {
    return (
      <div className="kroki-diagram-outer-container relative group overflow-hidden flex flex-col" style={{
        borderRadius: '0.5rem',
        border: currentAppTheme === 'dark' ? '1px solid #374151' : '1px solid #e5e7eb',
        boxShadow: 'none',
        outline: 'none',
        background: 'transparent'
      }}>
        <div className="kroki-diagram-inner-container p-2 overflow-x-auto grow" style={{
          backgroundColor: currentAppTheme === 'dark' ? '#1f2937' : '#ffffff',
          borderRadius: '0.5rem',
          border: 'none',
          boxShadow: 'none',
          outline: 'none'
        }}>
          <style>{`
          .kroki-diagram-svg-render svg {
            display: block;
            width: auto;
            height: 100%;
            max-width: 100%;
            margin: 0 auto;
          }
          .prose pre:has(.kroki-diagram-outer-container) {
            background: transparent !important;
            border: none !important;
            border-radius: 0 !important;
            padding: 0 !important;
            margin: 0 !important;
            box-shadow: none !important;
            outline: none !important;
          }
        `}</style>
        <div
          className="kroki-diagram-svg-render flex items-center justify-center overflow-hidden min-h-[200px]"
          dangerouslySetInnerHTML={{ __html: svgContent }}
        />
        <div className="absolute top-1 right-1 flex space-x-1 opacity-0 group-hover:opacity-100 transition-opacity duration-200 bg-slate-200 dark:bg-slate-700 p-1 rounded">
          <Button variant="ghost" size="icon" title="Download SVG" onClick={handleDownloadSvg}>
            <Download className="h-4 w-4 text-slate-600 dark:text-slate-300" />
          </Button>
          <Button variant="ghost" size="icon" title="Copy as Image" onClick={handleCopyAsImage} disabled={!!copyStatus}>
            {copyStatus ? <span className="text-xs text-slate-700 dark:text-slate-200">{copyStatus}</span> : <Copy className="h-4 w-4 text-slate-600 dark:text-slate-300" />}
          </Button>
          <Button variant="ghost" size="icon" title="Fullscreen" onClick={() => setShowFullscreenModal(true)}>
            <Maximize2 className="h-4 w-4 text-slate-600 dark:text-slate-300" />
          </Button>
          <Button variant="ghost" size="icon" title={showRawCode ? "Hide Code" : "Show Code"} onClick={handleToggleRawCode}>
            <CodeIcon className="h-4 w-4 text-slate-600 dark:text-slate-300" />
          </Button>
        </div>
        {showRawCode && (
          <div className="mt-0">
            <CodeBlock codeText={codeText} className={`language-${diagramType}`} isFallback={true}>
              {[codeText]}
            </CodeBlock>
          </div>
        )}
        </div>
        {showFullscreenModal && (
          <Dialog open={showFullscreenModal} onOpenChange={setShowFullscreenModal}>
            <DialogContent className="max-w-[95vw] w-[95vw] h-[95vh] flex flex-col p-2">
              <DialogHeader className="flex-shrink-0">
                <DialogTitle className="truncate">Fullscreen Diagram</DialogTitle>
                <DialogClose asChild>
                  <Button variant="ghost" size="icon" className="absolute top-2 right-2">
                    <Maximize2 className="h-4 w-4 transform rotate-45" />
                  </Button>
                </DialogClose>
              </DialogHeader>
              <style>{`
                .fullscreen-svg-container {
                  width: 100%;
                  height: 100%;
                  display: flex;
                  align-items: center;
                  justify-content: center;
                  overflow: auto;
                }
                .fullscreen-svg-inner-wrapper {
                  transition: transform 0.2s ease-out;
                  transform-origin: center center;
                  width: 100%;
                  height: 100%;
                  display: flex;
                  align-items: center;
                  justify-content: center;
                }
                .fullscreen-svg-inner-wrapper svg {
                  display: block;
                  width: 100%;
                  height: 100%;
                  object-fit: contain;
                }
              `}</style>
              <div className="flex-grow overflow-auto p-4 bg-background-50 relative fullscreen-svg-container">
                <div
                  style={{ transform: `translate(${fullscreenTranslateX}px, ${fullscreenTranslateY}px) scale(${fullscreenScale})` }}
                  dangerouslySetInnerHTML={{ __html: svgContent }}
                  className="fullscreen-svg-inner-wrapper"
                />
                <div className="absolute bottom-4 right-4 flex items-end space-x-2">
                  <div className="grid grid-cols-3 gap-1 p-1 rounded-md shadow-lg bg-white/70 dark:bg-black/70 backdrop-blur-sm">
                    <div></div>
                    <Button variant="ghost" size="icon" className="hover:bg-slate-200 dark:hover:bg-slate-700" onClick={() => handleFullscreenPan(0, PAN_STEP)} title="Pan Up">
                      <ArrowUp className="h-5 w-5" />
                    </Button>
                    <div></div>
                    <Button variant="ghost" size="icon" className="hover:bg-slate-200 dark:hover:bg-slate-700" onClick={() => handleFullscreenPan(PAN_STEP, 0)} title="Pan Left">
                      <ArrowLeft className="h-5 w-5" />
                    </Button>
                    <Button variant="ghost" size="icon" className="hover:bg-slate-200 dark:hover:bg-slate-700" onClick={handleFullscreenResetView} title="Reset View">
                      <RefreshCcw className="h-5 w-5" />
                    </Button>
                    <Button variant="ghost" size="icon" className="hover:bg-slate-200 dark:hover:bg-slate-700" onClick={() => handleFullscreenPan(-PAN_STEP, 0)} title="Pan Right">
                      <ArrowRight className="h-5 w-5" />
                    </Button>
                    <div></div>
                    <Button variant="ghost" size="icon" className="hover:bg-slate-200 dark:hover:bg-slate-700" onClick={() => handleFullscreenPan(0, -PAN_STEP)} title="Pan Down">
                      <ArrowDown className="h-5 w-5" />
                    </Button>
                    <div></div>
                  </div>
                  <div className="flex flex-col space-y-1 p-1 rounded-md shadow-lg bg-white/70 dark:bg-black/70 backdrop-blur-sm">
                    <Button variant="ghost" size="icon" className="hover:bg-slate-200 dark:hover:bg-slate-700" onClick={handleFullscreenZoomIn} title="Zoom In">
                      <ZoomIn className="h-5 w-5" />
                    </Button>
                    <Button variant="ghost" size="icon" className="hover:bg-slate-200 dark:hover:bg-slate-700" onClick={handleFullscreenZoomOut} title="Zoom Out">
                      <ZoomOut className="h-5 w-5" />
                    </Button>
                  </div>
                </div>
              </div>
              <div className="flex-shrink-0 flex items-center justify-center space-x-2 p-2 border-t">
                <Button variant="outline" size="sm" onClick={handleDownloadSvg}>
                  <Download className="h-4 w-4 mr-2" />
                  Download SVG
                </Button>
                <Button variant="outline" size="sm" onClick={handleCopyAsImage} disabled={!!copyStatus}>
                  {copyStatus === "Copying..." && <Loader2 className="h-4 w-4 mr-2 animate-spin text-slate-700 dark:text-slate-200" />}
                  {copyStatus === "Copied!" && <Copy className="h-4 w-4 mr-2 text-green-600 dark:text-green-400" />}
                  {copyStatus === "Copy failed." && <AlertTriangle className="h-4 w-4 mr-2 text-red-600 dark:text-red-400" />}
                  {!copyStatus && <Copy className="h-4 w-4 mr-2 text-slate-700 dark:text-slate-200" />}
                  <span className="text-slate-700 dark:text-slate-200">{copyStatus ? copyStatus : "Copy as Image"}</span>
                </Button>
                <Button variant="outline" size="sm" onClick={handleCopyCode} disabled={!!copyCodeStatus}>
                  {copyCodeStatus === "Copying..." && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
                  {copyCodeStatus === "Copied!" && <ClipboardCopy className="h-4 w-4 mr-2 text-green-600 dark:text-green-400" />}
                  {copyCodeStatus === "Failed!" && <AlertTriangle className="h-4 w-4 mr-2 text-red-600 dark:text-red-400" />}
                  {!copyCodeStatus && <ClipboardCopy className="h-4 w-4 mr-2" />}
                  <span className="text-slate-700 dark:text-slate-200">{copyCodeStatus ? copyCodeStatus : "Copy as Code"}</span>
                </Button>
              </div>
            </DialogContent>
          </Dialog>
        )}
      </div>
    );
  }

  return null;
};

export default KrokiDiagram;
