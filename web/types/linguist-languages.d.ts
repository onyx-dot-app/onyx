declare module "linguist-languages" {
  interface LinguistLanguage {
    name: string;
    type: string;
    extensions?: string[];
    filenames?: string[];
  }

  const languages: Record<string, LinguistLanguage>;
  export = languages;
}
