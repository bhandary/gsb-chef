const OPENAI_STORAGE_KEY = "gsb:chat:openaiApiKey";
const TAVILY_STORAGE_KEY = "gsb:chat:tavilyApiKey";
const HOST_STORAGE_KEY = "gsb:chat:providerKeyHost";

export type ProviderKeys = {
  openai: string;
  tavily: string;
};

function originOf(apiUrl: string): string | null {
  try {
    return new URL(apiUrl).origin;
  } catch {
    return null;
  }
}

export function readProviderKeys(apiUrl: string): ProviderKeys {
  const empty = { openai: "", tavily: "" };
  try {
    if (typeof window === "undefined") return empty;
    const storedHost = window.localStorage.getItem(HOST_STORAGE_KEY);
    const currentHost = originOf(apiUrl);
    if (!storedHost || !currentHost || storedHost !== currentHost) {
      return empty;
    }
    return {
      openai: window.localStorage.getItem(OPENAI_STORAGE_KEY) ?? "",
      tavily: window.localStorage.getItem(TAVILY_STORAGE_KEY) ?? "",
    };
  } catch {
    return empty;
  }
}

export function writeProviderKeys(apiUrl: string, keys: ProviderKeys): void {
  const host = originOf(apiUrl);
  if (typeof window === "undefined" || !host) return;
  window.localStorage.setItem(HOST_STORAGE_KEY, host);
  window.localStorage.setItem(OPENAI_STORAGE_KEY, keys.openai);
  window.localStorage.setItem(TAVILY_STORAGE_KEY, keys.tavily);
}
