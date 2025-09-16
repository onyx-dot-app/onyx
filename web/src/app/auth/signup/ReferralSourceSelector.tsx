"use client";
import React from "react";
import k from "./../../../i18n/keys";
import { useTranslation } from "@/hooks/useTranslation";

import { useState } from "react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/admin/connectors/Field";

interface ReferralSourceSelectorProps {
  defaultValue?: string;
}

const ReferralSourceSelector: React.FC<ReferralSourceSelectorProps> = ({
  defaultValue,
}) => {
  const { t } = useTranslation();
  const [referralSource, setReferralSource] = useState(defaultValue);

  const referralOptions = [
    { value: t(k.SEARCH1), label: t(k.SEARCH_ENGINE_GOOGLE_BING) },
    { value: t(k.FRIEND), label: t(k.FRIEND_COLLEAGUE) },
    { value: t(k.LINKEDIN), label: t(k.LINKEDIN1) },
    { value: t(k.TWITTER), label: t(k.TWITTER1) },
    { value: t(k.HACKERNEWS), label: t(k.HACKERNEWS1) },
    { value: t(k.REDDIT), label: t(k.REDDIT1) },
    { value: t(k.YOUTUBE), label: t(k.YOUTUBE1) },
    { value: t(k.PODCAST), label: t(k.PODCAST1) },
    { value: t(k.BLOG), label: t(k.ARTICLE_BLOG) },
    { value: t(k.ADS), label: t(k.ADVERTISEMENTS) },
    { value: t(k.OTHER), label: t(k.OTHER1) },
  ];

  const handleChange = (value: string) => {
    setReferralSource(value);
    const cookies = require("js-cookie");
    cookies.set("referral_source", value, {
      expires: 365,
      path: "/",
      sameSite: "strict",
    });
  };

  return (
    <div className="w-full max-w-sm gap-y-2 flex flex-col mx-auto">
      <Label className="text-text-950" small={false}>
        {t(k.HOW_DID_YOU_HEAR_ABOUT_US)}
      </Label>
      <Select value={referralSource} onValueChange={handleChange}>
        <SelectTrigger
          id="referral-source"
          className="w-full border-background-300 rounded-md shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
        >
          <SelectValue placeholder={t(k.SELECT_FROM_LIST)} />
        </SelectTrigger>
        <SelectContent className="max-h-60 overflow-y-auto">
          {referralOptions.map((option) => (
            <SelectItem
              key={option.value}
              value={option.value}
              className="py-2 px-3 hover:bg-indigo-100 cursor-pointer"
            >
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
};

export default ReferralSourceSelector;
