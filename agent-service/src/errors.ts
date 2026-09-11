export class ModelFailure extends Error {
  readonly code: string;
  readonly retryable: boolean;
  constructor(message: string, status?: number) {
    super(message);
    status ??= Number(/^(\d{3})\b/.exec(message)?.[1]) || undefined;
    if (/context.{0,20}(length|window)|maximum context/i.test(message)) {
      this.code = "CONTEXT_WINDOW_EXCEEDED";
      this.retryable = false;
    } else if (status === 401 || status === 403) {
      this.code = "AUTHENTICATION_ERROR";
      this.retryable = false;
    } else if (status === 429) {
      this.code = "RATE_LIMIT_ERROR";
      this.retryable = true;
    } else {
      this.code = "MODEL_ERROR";
      this.retryable = status === undefined || status >= 500 || status === 408;
    }
  }
}
