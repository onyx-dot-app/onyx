import React from "react";

interface ErrorBoundaryProps {
  componentName: string;
  children: React.ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

/**
 * Per-component error boundary.
 * Prevents a single broken component from crashing the entire GenUI output.
 */
export class ErrorBoundary extends React.Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div
          style={{
            padding: "8px 12px",
            border: "1px solid #ef4444",
            borderRadius: "4px",
            backgroundColor: "#fef2f2",
            color: "#991b1b",
            fontSize: "13px",
            fontFamily: "monospace",
          }}
        >
          <strong>{this.props.componentName}</strong> failed to render
          {this.state.error && (
            <div style={{ marginTop: 4, opacity: 0.8 }}>
              {this.state.error.message}
            </div>
          )}
        </div>
      );
    }

    return this.props.children;
  }
}
