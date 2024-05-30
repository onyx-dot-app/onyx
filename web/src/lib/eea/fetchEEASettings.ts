import { fetchSS } from "@/lib/utilsSS";


export async function fetchEEASettings(){
    const resp = await fetchSS("/eea_config/get_eea_config");
    let eea_config = {disclaimer:{disclaimer_title:"", disclaimer_text:""}};
    if (resp?.ok){
        eea_config = await resp.json();
    }
    const disclaimerTitle = eea_config?.disclaimer?.disclaimer_title || "";
    const disclaimerText = eea_config?.disclaimer?.disclaimer_title || "";

    return {eea_config: eea_config, disclaimerText:disclaimerText, disclaimerTitle:disclaimerTitle};
}
