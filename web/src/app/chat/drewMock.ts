import { PacketType, SendMessageParams } from "./lib";
import { buildActionPacket } from "./deepResearchAction";

export async function* mockSendMessage(
  params: SendMessageParams
): AsyncGenerator<PacketType, void, unknown> {
  // TODO: add aborthandler
  yield* mockSseStream(params);
}

function getRandomNumber(min: number, max: number) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

const delay = (ms: number) => {
  return new Promise((resolve) => setTimeout(resolve, ms));
};
async function* mockSseStream(
  _params: SendMessageParams
): AsyncGenerator<PacketType, void, unknown> {
  await delay(100);
  // Run server packet simulation here
  const userMessageId = getRandomNumber(1, 1000);

  yield {
    user_message_id: userMessageId,
    reserved_assistant_message_id: userMessageId + 1,
  };

  yield buildActionPacket("thinking", {
    id: "first-thinking",
    thinking: "Thinking about what makes a shoe good",
  });

  await delay(1000);

  yield buildActionPacket("web_search", {
    collapsed: false,
    id: "first-web-search",
    query: "Best shoes to buy",
    results: [],
  });
  await delay(1000);
  yield buildActionPacket("web_search", {
    collapsed: false,
    id: "first-web-search",
    query: "Best shoes to buy",
    results: [
      {
        title: "(Reddit) Shoe Reviews",
        url: "https://www.reddit.com/r/ShoeReviews/",
      },
    ],
  });
  await delay(1000);
  yield buildActionPacket("web_search", {
    collapsed: false,
    id: "first-web-search",
    query: "Best shoes to buy",
    results: [
      {
        title: "(Reddit) Shoe Reviews",
        url: "https://www.reddit.com/r/ShoeReviews/",
      },
      {
        title: "Nike. Just Do It. Nike.com",
        url: "https://www.nike.com/",
      },
    ],
  });

  await delay(200);
  yield buildActionPacket("run_command", {
    id: "parse-nike",
    cmd: `curl https://www.nike.com/`,
    collapsed: false,
    result: "",
  });

  await delay(200);
  yield buildActionPacket("run_command", {
    id: "parse-nike",
    cmd: `curl https://www.nike.com/`,
    result: `
<!DOCTYPE html><html lang="en-US"><head><meta charSet="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=2.0"/><meta name="keywords" content="nike"/><meta name="robots" content="index, follow"/><meta name="description" content="Nike delivers innovative products, experiences and services to inspire athletes."/><meta http-equiv="content-language" content="en-US"/><meta name="application-name" content="Nike.com"/><meta property="og:description" content="Nike delivers innovative products, experiences and services to inspire athletes."/><meta property="og:image" content="https://c.static-nike.com/a/images/w_1920,c_limit/bzl2wmsfh7kgdkufrrjq/image.jpg"/><meta property="og:locale" content="en-US"/><meta property="og:site_name" content="Nike.com"/><meta property="og:title" content="Nike. Just Do It"/><meta property="og:type" content="website"/><meta property="og:url" content="https://www.nike.com/?cid=4942550&amp;cp=usns_aff_nike__PID_100481284_Afterpay+US+Inc&amp;cjevent=44610f7447e711f082d100ae0a1cb827&amp;_forward_params=1&amp;pcn=cj_mobile_inactivity-0d&amp;_smtype=3&amp;psid=100481284&amp;pcrn=CJ&amp;cl=44610f7447e711f082d100ae0a1cb827&amp;pcrid=17047842&amp;psn=Afterpay+US+Inc"/><meta name="twitter:card" content="summary_large_image"/><meta name="twitter:creator" content="@nike"/><meta name="twitter:description" content="Nike delivers innovative products, experiences and services to inspire athletes."/><meta name="twitter:image" content="https://c.static-nike.com/a/images/w_1920,c_limit/bzl2wmsfh7kgdkufrrjq/image.jpg"/><meta name="twitter:site" content="@nike"/><meta name="twitter:title" content="Nike. Just Do It"/><link href="https://www.nike.com/favicon.ico?v=1" rel="icon" type="image/x-icon"/><link href="https://www.nike.com/android-icon-192x192.png" rel="icon" sizes="192x192" type="image/png"/><link href="https://www.nike.com/android-icon-128x128.png" rel="icon" sizes="128x128" type="image/png"/><link href="https://www.nike.com/apple-touch-icon.png" rel="apple-touch-icon" type="image/png"/><link href="https://www.nike.com/apple-touch-icon-76x76-precomposed.png" rel="apple-touch-icon" sizes="76x76" type="image/png"/><link href="https://www.nike.com/apple-touch-icon-120x120-precomposed.png" rel="apple-touch-icon" sizes="120x120" type="image/png"/><link href="https://www.nike.com/apple-touch-icon-152x152-precomposed.png" rel="apple-touch-icon" sizes="152x152" type="image/png"/><link href="https://insights-collector.newrelic.com/" rel="dns-prefetch"/><link href="https://c.static-nike.com/" rel="dns-prefetch"/><link href="https://cdnjs.cloudflare.com/" rel="dns-prefetch"/><link href="https://secure-store.nike.com/" rel="dns-prefetch"/><link href="https://web.nike.com/" rel="dns-prefetch"/><link href="https://static.nike.com/" rel="dns-prefetch"/><link href="https://api.segment.io/" rel="dns-prefetch"/><link href="https://api.nike.com" rel="dns-prefetch"/><link href="https://connect.facebook.net/" rel="dns-prefetch"/><link href="https://analytics.nike.com/" rel="dns-prefetch"/><link as="font" crossorigin="crossorigin" href="https://www.nike.com/static/ncss/5.0/dotcom/fonts/Nike-Futura.woff2" rel="preload" type="font/woff2"/><link href="https://www.nike.com/" rel="canonical"/><title>Nike. Just Do It. Nike.com</title><meta name="next-head-count" content="40"/><script id="new-relic-browser-agent" type="text/javascript">window.NREUM||(NREUM={});NREUM.info = {"agent":"","beacon":"bam.nr-data.net","errorBeacon":"bam.nr-data.net","licenseKey":"NRBR-d074912dd348988f83d","applicationID":"175756206","agentToken":null,"applicationTime":151.116167,"transactionName":"ZVdXbUtXXBIHVUNfXlwde1ZLW1MND0xSUmRAWxoT","queueTime":0,"ttGuid":"5f1693e395762bf5"}; (window.NREUM||(NREUM={})).init={privacy:{cookies_enabled:true},ajax:{deny_list:["bam.nr-data.net"]}};(window.NREUM||(NREUM={})).loader_config={xpid:"UwcDVlVUGwIHUVZXAQMHUA==",licenseKey:"NRBR-d074912dd348988f83d",applicationID:"175756206"};;/*
`,
    collapsed: false,
  });
  const finalAnswer = "This is a final answer. All shoes are good";
  const words = finalAnswer.split(" ");

  for (const word of words) {
    await delay(200);
    yield {
      answer_piece: word + " ",
    };
  }
}
