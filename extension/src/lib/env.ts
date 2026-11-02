declare const __JOBBOT_API_ORIGIN__: string;
declare const __JOBBOT_WEB_ORIGIN__: string;

export const API_ORIGIN = __JOBBOT_API_ORIGIN__;
export const WEB_ORIGIN = __JOBBOT_WEB_ORIGIN__;
export const TOKEN_KEY = "jobbot_token";

/**
 * "Auto-fill" tailors a resume per job, which uses AI credits. The server refuses it
 * unless the owner switched it on for that member (Members page).
 */
export const AUTOFILL_ENABLED = true;
