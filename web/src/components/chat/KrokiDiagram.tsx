"use client";

import React, { useState, useEffect, useCallback } from 'react';
import { AlertTriangle, Loader2, Download, Copy, Maximize2, Code as CodeIcon, ClipboardCopy, AlertCircle, RefreshCw } from 'lucide-react'; // Added AlertCircle, RefreshCw
import { Button } from "@/components/ui/button";
import { CodeBlock } from "@/app/chat/message/CodeBlock"; // Import CodeBlock
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogClose,
} from "@/components/ui/dialog"; // For fullscreen modal
import { KROKI_SUPPORTED_LANGUAGES } from "@/lib/kroki_constants";


interface KrokiDiagramProps {
  diagramType: string;
  codeText: string;
  onFeatureDisabled: () => void; // Added callback prop
}

const KrokiDiagram: React.FC<KrokiDiagramProps> = ({ diagramType, codeText, onFeatureDisabled }) => {
  const [svgContent, setSvgContent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null); // Will store the error message
  const [renderFallbackAsCodeBlock, setRenderFallbackAsCodeBlock] = useState(false); // New state for fallback
  const [isLoading, setIsLoading] = useState(true);
  const [showRawCode, setShowRawCode] = useState(false);
  const [showFullscreenModal, setShowFullscreenModal] = useState(false);
  const [copyStatus, setCopyStatus] = useState<string | null>(null);
  const [copyCodeStatus, setCopyCodeStatus] = useState<string | null>(null); // New state for copy code status
  const [currentAppTheme, setCurrentAppTheme] = useState<'light' | 'dark'>(() => 
    typeof window !== 'undefined' && document.documentElement.classList.contains('dark') ? 'dark' : 'light'
  );

  // Effect to listen for theme changes on the HTML element
  useEffect(() => {
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
      // Attempt to remove foreignObject elements to prevent canvas tainting
      // This may affect diagrams that use HTML for text rendering (e.g., some Mermaid charts)
      const cleanedSvgContent = svgContent.replace(/<foreignObject[\s\S]*?<\/foreignObject>/g, '');

      // 1. Create an image element
      const img = new Image();
      img.crossOrigin = "anonymous"; 
      const svgBlob = new Blob([cleanedSvgContent], { type: 'image/svg+xml;charset=utf-8' });
      const url = URL.createObjectURL(svgBlob);
  
      img.onload = async () => {
        // 2. Create a canvas
        const canvas = document.createElement('canvas');
        // Optional: Add a small padding or ensure dimensions are sufficient
        const scale = window.devicePixelRatio || 1; // Consider device pixel ratio for sharpness
        canvas.width = img.width * scale;
        canvas.height = img.height * scale;
        const ctx = canvas.getContext('2d');
        if (!ctx) {
          throw new Error('Could not get canvas context');
        }
        ctx.scale(scale, scale);
        ctx.drawImage(img, 0, 0);
  
        // 3. Convert canvas to blob
        canvas.toBlob(async (blob) => {
          if (!blob) {
            throw new Error('Canvas to Blob conversion failed');
          }
          // 4. Use Clipboard API
          try {
            await navigator.clipboard.write([
              new ClipboardItem({ 'image/png': blob })
            ]);
            setCopyStatus("Copied!");
          } catch (clipErr) {
            console.error('Clipboard API error:', clipErr);
            setCopyStatus("Copy failed.");
          } finally {
            URL.revokeObjectURL(url); // Clean up object URL
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


  useEffect(() => {
    if (!KROKI_SUPPORTED_LANGUAGES.has(diagramType)) {
      setError(`Unsupported diagram type: ${diagramType}`);
      setIsLoading(false);
      return;
    }

    const fetchDiagram = async () => {
      setIsLoading(true);
      setError(null);
      setSvgContent(null);

      let processedCodeText = codeText;
      const isDarkMode = currentAppTheme === 'dark';

      if (diagramType === 'mermaid') {
        const mermaidTheme = isDarkMode ? 'dark' : 'default';
        processedCodeText = `%%{init: {'theme':'${mermaidTheme}'}}%%\n${codeText}`;
      } else if ((diagramType === 'plantuml' || diagramType === 'c4plantuml') && isDarkMode) {
        // Basic dark theme for PlantUML. For light mode, PlantUML's default is usually fine.
        // More comprehensive themes can be very long, so keeping it simple.
        const plantUmlDarkTheme = 'skinparam backgroundColor #333333\nskinparam shadowing false\nskinparam FontColor #FFFFFF\nskinparam ArrowColor #CCCCCC\nskinparam ActorBorderColor #CCCCCC\nskinparam ParticipantBorderColor #CCCCCC\nskinparam NoteBorderColor #CCCCCC\nskinparam ClassBorderColor #CCCCCC\n';
        processedCodeText = `${plantUmlDarkTheme}${codeText}`;
      }
      // Other diagram types could be added here if simple theme injection methods are identified

      try {
        const response = await fetch(`/api/kroki/${diagramType}`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ content: processedCodeText }), // Use processedCodeText
        });

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({})); // Gracefully handle non-JSON error responses
          const errorMessage = errorData.detail || errorData.error || `Failed to render diagram (status: ${response.status})`;

          // If Kroki service itself is not found or explicitly disabled by backend
          if (response.status === 404 || (errorMessage && errorMessage.toLowerCase().includes("kroki service not enabled"))) {
            onFeatureDisabled();
          }
          throw new Error(errorMessage);
        }

        const result = await response.json();
        if (result.svg) {
          // SVG customization code removed as per feedback
          setSvgContent(result.svg);
          setRenderFallbackAsCodeBlock(false);
        } else {
          // Kroki returned an error in the JSON response (e.g. syntax error)
          const krokiErrorMsg = result.error ? `Kroki Error: ${result.error} (Type: ${result.error_type})` : 'Unexpected response from Kroki service.';
          console.warn(krokiErrorMsg);
          setError(krokiErrorMsg); // Store error for potential display if needed, but primarily trigger fallback
          setRenderFallbackAsCodeBlock(true);
        }
      } catch (err) {
        // Network error or non-JSON error response from fetch
        const fetchErrorMsg = err instanceof Error ? err.message : 'An unknown error occurred during fetch.';
        console.error("Error fetching Kroki diagram:", err);
        setError(fetchErrorMsg);
        setRenderFallbackAsCodeBlock(true);
      } finally {
        setIsLoading(false);
      }
    };

    fetchDiagram();
  }, [diagramType, codeText, currentAppTheme, onFeatureDisabled]); // Added onFeatureDisabled to deps

  if (isLoading) {
    return (
      <div className="kroki-diagram-loading-container flex items-center justify-center p-4 bg-white">
        <Loader2 className="h-6 w-6 animate-spin" />
      </div>
    );
  }

  // If rendering failed, fall back to showing the original code in a standard CodeBlock
  if (renderFallbackAsCodeBlock) {
    // Optionally, you could display the 'error' message above the CodeBlock if desired
    // For now, just rendering the CodeBlock as per feedback.
    // The CodeBlock component itself should handle its own styling including the header.
    // Pass codeText as an array to children to ensure CodeBlock renders it as block content.
    return (
      <CodeBlock codeText={codeText} className={`language-${diagramType}`} isFallback={true}>
        {[codeText]}
      </CodeBlock>
    );
  }

  if (svgContent) {
    return (
      <div className="kroki-diagram-container relative group p-2 bg-white overflow-x-auto">
        {/* Style for the normal view SVG rendering to respect max-height and scale proportionally */}
        <style>{`
          .kroki-diagram-svg-render svg {
            display: block;
            width: auto;     /* Calculate width based on height and aspect ratio */
            height: 100%;    /* Attempt to fill the parent container's height */
            max-width: 100%; /* Ensure the auto-calculated width doesn't exceed parent's width */
            margin: 0 auto;  /* Center the SVG horizontally if its width is less than the container's width */
          }
        `}</style>
        <div
          className="kroki-diagram-svg-render overflow-hidden" // Ensure no flex here, max-h-96 removed
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
          // Removed h4 heading, border-t, and pt-2. 
          // The CodeBlock itself, when isFallback=true, will have my-2 from prose styling.
          // If further spacing adjustment is needed, it can be done here or on CodeBlock.
          // For now, relying on CodeBlock's inherent spacing when it's a fallback.
          <div className="mt-0"> {/* Or simply remove this div if CodeBlock's margin is sufficient */}
            <CodeBlock codeText={codeText} className={`language-${diagramType}`} isFallback={true}>
              {[codeText]}
            </CodeBlock>
          </div>
        )}

        {showFullscreenModal && (
          <Dialog open={showFullscreenModal} onOpenChange={setShowFullscreenModal}>
            <DialogContent className="max-w-[95vw] w-[95vw] h-[95vh] flex flex-col p-2">
              <DialogHeader className="flex-shrink-0">
                <DialogTitle className="truncate">Fullscreen Diagram</DialogTitle>
                <DialogClose asChild>
                  <Button variant="ghost" size="icon" className="absolute top-2 right-2">
                    <Maximize2 className="h-4 w-4 transform rotate-45" /> {/* Simple close icon */}
                  </Button>
                </DialogClose>
              </DialogHeader>
              <style>{`
                .fullscreen-svg-inner-wrapper {
                  width: 100%; /* Ensure the wrapper takes full space */
                  height: 100%;
                  display: flex; /* Use flex to center the SVG child */
                  align-items: center;
                  justify-content: center;
                }
                .fullscreen-svg-inner-wrapper svg {
                  display: block;
                  width: 100%;   /* Attempt to fill the container's width */
                  height: 100%;  /* Attempt to fill the container's height */
                  /* preserveAspectRatio="xMidYMid meet" (expected from Kroki) will handle scaling */
                }
              `}</style>
              <div className="flex-grow overflow-auto p-4 bg-background-50"> 
                <div
                  dangerouslySetInnerHTML={{ __html: svgContent }}
                  className="fullscreen-svg-inner-wrapper" 
                />
              </div>
              {/* Footer for buttons in fullscreen modal */}
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

  return null; // Should not happen if logic is correct
};

export default KrokiDiagram;
