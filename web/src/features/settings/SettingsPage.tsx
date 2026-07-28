import type { FC } from "react";
import { useEffect, useState } from "react";
import type { LLMSettings } from "../../lib/types";
import { DEFAULT_LLM_SETTINGS } from "../../lib/types";
import styles from "./SettingsPage.module.css";

const STORAGE_KEY = "llull:settings:llm";

function loadSettings(): LLMSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw) as LLMSettings;
  } catch {
    // ignore parse errors
  }
  return { ...DEFAULT_LLM_SETTINGS };
}

function saveSettings(s: LLMSettings): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
  } catch {
    // ignore
  }
}

const MODEL_PRESETS: Record<string, string[]> = {
  openai: ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
  anthropic: [
    "claude-opus-4-5",
    "claude-sonnet-4-5",
    "claude-haiku-4-5",
    "claude-3-7-sonnet-20250219",
  ],
  ollama: ["llama3.2", "mistral", "gemma2", "qwen2.5"],
};

export const SettingsPage: FC = () => {
  const [settings, setSettings] = useState<LLMSettings>(loadSettings);
  const [saved, setSaved] = useState(false);

  const handleChange = <K extends keyof LLMSettings>(key: K, value: LLMSettings[K]) => {
    setSettings((prev) => ({ ...prev, [key]: value }));
    setSaved(false);
  };

  const handleProviderChange = (provider: LLMSettings["provider"]) => {
    const firstModel = MODEL_PRESETS[provider]?.[0] ?? "";
    setSettings((prev) => ({ ...prev, provider, model: firstModel }));
    setSaved(false);
  };

  const handleSave = () => {
    saveSettings(settings);
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  };

  const handleReset = () => {
    setSettings({ ...DEFAULT_LLM_SETTINGS });
    setSaved(false);
  };

  return (
    <div className={styles.page}>
      <h1 className={styles.title}>Settings</h1>
      <p className={styles.subtitle}>
        Configure your LLM provider and preferences. Settings are stored locally in your browser.
      </p>

      <div className={styles.warningNote}>
        ⚠️ API keys are stored in localStorage — do not use on shared or public devices.
      </div>

      <div className={styles.section} style={{ marginTop: "1.5rem" }}>
        <h2 className={styles.sectionTitle}>LLM Configuration</h2>
        <div className={styles.formGrid}>
          <div className={styles.formGroup}>
            <label className={styles.label} htmlFor="provider">Provider</label>
            <select
              id="provider"
              className={styles.select}
              value={settings.provider}
              onChange={(e) => handleProviderChange(e.target.value as LLMSettings["provider"])}
            >
              <option value="anthropic">Anthropic</option>
              <option value="openai">OpenAI</option>
              <option value="ollama">Ollama (local)</option>
            </select>
          </div>

          <div className={styles.formGroup}>
            <label className={styles.label} htmlFor="model">Model</label>
            <select
              id="model"
              className={styles.select}
              value={settings.model}
              onChange={(e) => handleChange("model", e.target.value)}
            >
              {(MODEL_PRESETS[settings.provider] ?? []).map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
            <p className={styles.hint}>
              Or type a custom model name — edit the value directly in the API service .env
            </p>
          </div>

          {settings.provider !== "ollama" && (
            <div className={styles.formGroup}>
              <label className={styles.label} htmlFor="apiKey">API Key</label>
              <input
                id="apiKey"
                className={styles.input}
                type="password"
                placeholder={`Enter your ${settings.provider === "openai" ? "OpenAI" : "Anthropic"} API key`}
                value={settings.apiKey}
                onChange={(e) => handleChange("apiKey", e.target.value)}
              />
              <p className={styles.hint}>
                Used by the Llull service. Configure in the service .env file for production.
              </p>
            </div>
          )}

          {settings.provider === "ollama" && (
            <div className={styles.formGroup}>
              <label className={styles.label} htmlFor="ollamaUrl">Ollama Base URL</label>
              <input
                id="ollamaUrl"
                className={styles.input}
                type="url"
                placeholder="http://localhost:11434"
                value={settings.ollamaBaseUrl}
                onChange={(e) => handleChange("ollamaBaseUrl", e.target.value)}
              />
            </div>
          )}
        </div>
      </div>

      <div className={styles.section}>
        <h2 className={styles.sectionTitle}>API Endpoint</h2>
        <div className={styles.formGrid}>
          <div className={styles.formGroup}>
            <label className={styles.label}>API Base URL</label>
            <input
              className={styles.input}
              type="text"
              value={import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000"}
              readOnly
            />
            <p className={styles.hint}>
              Set via <code>VITE_API_BASE_URL</code> environment variable in <code>.env.local</code>
            </p>
          </div>
        </div>
      </div>

      <div className={styles.actions}>
        <button className="btn btn-primary" onClick={handleSave}>
          💾 Save Settings
        </button>
        <button className="btn btn-secondary" onClick={handleReset}>
          Reset to Defaults
        </button>
        {saved && <span className={styles.savedMsg}>✅ Settings saved!</span>}
      </div>
    </div>
  );
};
