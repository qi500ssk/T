export type InterfaceScale = "90" | "100" | "110";

export interface AppearancePreferences {
  scale: InterfaceScale;
  reduceMotion: boolean;
}

export const APPEARANCE_STORAGE_KEY = "personal-ai-appearance";
export const DEFAULT_APPEARANCE: AppearancePreferences = {
  scale: "100",
  reduceMotion: false,
};

export function readAppearance(): AppearancePreferences {
  try {
    const raw = JSON.parse(localStorage.getItem(APPEARANCE_STORAGE_KEY) || "{}");
    return {
      scale: ["90", "100", "110"].includes(raw.scale) ? raw.scale : "100",
      reduceMotion: Boolean(raw.reduceMotion),
    };
  } catch {
    return DEFAULT_APPEARANCE;
  }
}

export function applyAppearance(value: AppearancePreferences): void {
  document.documentElement.style.fontSize = `${16 * (Number(value.scale) / 100)}px`;
  document.documentElement.dataset.reduceMotion = value.reduceMotion ? "true" : "false";
}

export function saveAppearance(value: AppearancePreferences): void {
  localStorage.setItem(APPEARANCE_STORAGE_KEY, JSON.stringify(value));
  applyAppearance(value);
}
