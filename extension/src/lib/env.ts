declare const __JOBBOT_API_ORIGIN__: string;
declare const __JOBBOT_WEB_ORIGIN__: string;

export const API_ORIGIN = __JOBBOT_API_ORIGIN__;
export const WEB_ORIGIN = __JOBBOT_WEB_ORIGIN__;
export const TOKEN_KEY = "jobbot_token";
/** Where the JobBot website keeps its session token (frontend/src/auth/api.ts TOKEN_KEY). */
export const WEB_TOKEN_KEY = "jobbot_access_token";

/**
 * "Auto-fill" tailors a resume per job, which uses AI credits. The server refuses it
 * unless the owner switched it on for that member (Members page).
 */
export const AUTOFILL_ENABLED = true;
