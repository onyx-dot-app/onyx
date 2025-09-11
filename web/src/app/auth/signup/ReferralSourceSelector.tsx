"use client";
import i18n from "@/i18n/init";
import k from "./../../../i18n/keys";

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
  const [referralSource, setReferralSource] = useState(defaultValue);

  const referralOptions = [
    { value: i18n.t(k.SEARCH1), label: i18n.t(k.SEARCH_ENGINE_GOOGLE_BING) },
    { value: i18n.t(k.FRIEND), label: i18n.t(k.FRIEND_COLLEAGUE) },
    { value: i18n.t(k.LINKEDIN), label: i18n.t(k.LINKEDIN1) },
    { value: i18n.t(k.TWITTER), label: i18n.t(k.TWITTER1) },
    { value: i18n.t(k.HACKERNEWS), label: i18n.t(k.HACKERNEWS1) },
    { value: i18n.t(k.REDDIT), label: i18n.t(k.REDDIT1) },
    { value: i18n.t(k.YOUTUBE), label: i18n.t(k.YOUTUBE1) },
    { value: i18n.t(k.PODCAST), label: i18n.t(k.PODCAST1) },
    { value: i18n.t(k.BLOG), label: i18n.t(k.ARTICLE_BLOG) },
    { value: i18n.t(k.ADS), label: i18n.t(k.ADVERTISEMENTS) },
    { value: i18n.t(k.OTHER), label: i18n.t(k.OTHER1) },
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
        {i18n.t(k.HOW_DID_YOU_HEAR_ABOUT_US)}
      </Label>
      <Select value={referralSource} onValueChange={handleChange}>
        <SelectTrigger
          id="referral-source"
          className="w-full border-background-300 rounded-md shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
        >
          <SelectValue placeholder={i18n.t(k.SELECT_FROM_LIST)} />
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
