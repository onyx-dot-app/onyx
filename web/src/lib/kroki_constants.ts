// Defines the set of supported diagram languages for Kroki integration.
// This list should be kept in sync with backend configurations if possible,
// or ideally fetched from the backend in a future enhancement.

export const KROKI_SUPPORTED_LANGUAGES: Set<string> = new Set([
  "blockdiag", "seqdiag", "actdiag", "nwdiag", "packetdiag", "rackdiag",
  "graphviz", "pikchr", "erd", "excalidraw", "vega", "vegalite",
  "ditaa", "mermaid", "nomnoml", "plantuml", "bpmn", "bytefield",
  "wavedrom", "svgbob", "c4plantuml", "structurizr", "umlet",
  "wireviz", "symbolator"
]);
