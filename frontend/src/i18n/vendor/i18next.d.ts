interface I18next {
  language: string;
  resolvedLanguage?: string;
  init(options: Record<string, unknown>): Promise<unknown>;
  t(key: string, options?: Record<string, unknown>): string;
  exists(key: string, options?: Record<string, unknown>): boolean;
  changeLanguage(language: string): Promise<unknown>;
  on(event: string, listener: (language: string) => void): void;
  off(event: string, listener: (language: string) => void): void;
  addResourceBundle(language: string, namespace: string, resources: Record<string, string>, deep?: boolean, overwrite?: boolean): void;
}
declare const i18next: I18next;
export default i18next;
