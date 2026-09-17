"use client";

import { useState } from "react";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { Label } from "@/components/Field";
import { useTranslations } from "next-intl";

interface ReferralSourceSelectorProps {
  defaultValue?: string;
}

const REFERRAL_OPTION_VALUES = [
  "search",
  "friend",
  "linkedin",
  "twitter",
  "hackernews",
  "reddit",
  "youtube",
  "podcast",
  "blog",
  "ads",
  "other",
] as const;

export default function ReferralSourceSelector({
  defaultValue,
}: ReferralSourceSelectorProps) {
  const t = useTranslations("auth");
  const [referralSource, setReferralSource] = useState(defaultValue);

  const referralOptionLabels = {
    search: t("signup.referralOptionSearch.label"),
    friend: t("signup.referralOptionFriend.label"),
    linkedin: t("signup.referralOptionLinkedin.label"),
    twitter: t("signup.referralOptionTwitter.label"),
    hackernews: t("signup.referralOptionHackernews.label"),
    reddit: t("signup.referralOptionReddit.label"),
    youtube: t("signup.referralOptionYoutube.label"),
    podcast: t("signup.referralOptionPodcast.label"),
    blog: t("signup.referralOptionBlog.label"),
    ads: t("signup.referralOptionAds.label"),
    other: t("signup.referralOptionOther.label"),
  } satisfies Record<(typeof REFERRAL_OPTION_VALUES)[number], string>;

  const referralOptions = REFERRAL_OPTION_VALUES.map((value) => ({
    value,
    label: referralOptionLabels[value],
  }));

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
    <div className="w-full gap-y-2 flex flex-col">
      <Label className="text-text-950" small={false}>
        {t("signup.referralQuestion.label")}
      </Label>
      <InputSelect value={referralSource} onValueChange={handleChange}>
        <InputSelect.Trigger
          placeholder={t("signup.referralPlaceholder.placeholder")}
        />

        <InputSelect.Content>
          {referralOptions.map((option) => (
            <InputSelect.Item key={option.value} value={option.value}>
              {option.label}
            </InputSelect.Item>
          ))}
        </InputSelect.Content>
      </InputSelect>
    </div>
  );
}
