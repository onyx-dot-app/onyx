import { JSX } from "react";
import * as Yup from "yup";

export type FormBodyBuilder<T extends Yup.AnyObject> = (
  values: T
) => JSX.Element;

export type RequireAtLeastOne<T, Keys extends keyof T = keyof T> = Pick<
  T,
  Exclude<keyof T, Keys>
> &
  {
    [K in Keys]-?: Required<Pick<T, K>> & Partial<Pick<T, Exclude<Keys, K>>>;
  }[Keys];
