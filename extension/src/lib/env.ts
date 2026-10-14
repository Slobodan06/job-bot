declare const __JOBBOT_API_ORIGIN__: string;
declare const __JOBBOT_WEB_ORIGIN__: string;

export const API_ORIGIN = __JOBBOT_API_ORIGIN__;
export const WEB_ORIGIN = __JOBBOT_WEB_ORIGIN__;
export const TOKEN_KEY = "jobbot_token";

/**
 * "Quick fill" / "Tailor & fill" use OpenAI credits and are switched off for now.
 * To bring them back: set this to true, rebuild the extension, and set
 * EXTENSION_AUTOFILL_ENABLED=1 on the server (it refuses these calls otherwise).
 */
export const AUTOFILL_ENABLED = false;
