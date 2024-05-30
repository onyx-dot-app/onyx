import { fetchSS } from "@/lib/utilsSS";


export async function fetchEEASettings(){
    const resp = await fetchSS("/eea_config/get_eea_config");
    //let eea_config = {disclaimer:{disclaimer_title:"", disclaimer_text:""},footer:{footer_html:""}};
    let eea_config = undefined;
    let config = {config:""}
    if (resp?.ok){
        config = await resp.json();
        eea_config = JSON.parse(config?.config)
    }
    
    const disclaimerTitle = eea_config?.disclaimer?.disclaimer_title || "";
    const disclaimerText = eea_config?.disclaimer?.disclaimer_text || "";
    const footerHtml = eea_config?.footer?.footer_html || '<a class="py-4" href="https://Danswer.ai" target="_blank"><div class="flex"><div class="h-[32px] w-[30px]"><Image src="/logo.png" alt="Logo" width="1419" height="1520" /></div><h3 class="flex text-l text-strong my-auto">&nbsp;Powered by Danswer.ai</h3></div></a>';
    return {eea_config: eea_config, disclaimerText:disclaimerText, disclaimerTitle:disclaimerTitle, footerHtml: footerHtml};
}
