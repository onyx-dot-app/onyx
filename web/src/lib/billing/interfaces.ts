export interface BillingInformation {
  status: string;
  trial_end: Date | null;
  current_period_end: Date;
  payment_method_enabled: boolean;
  cancel_at_period_end: boolean;
  current_period_start: Date;
  number_of_seats: number;
  canceled_at: Date | null;
  trial_start: Date | null;
  seats: number;
}

export enum BillingStatus {
  TRIALING = "trialing",
  ACTIVE = "active",
  CANCELLED = "cancelled",
  EXPIRED = "expired",
}
