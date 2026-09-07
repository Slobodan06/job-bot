import { defineManifest } from "@crxjs/vite-plugin";

import pkg from "./package.json";

// The API origin the extension talks to. Override at build time:
//   JOBBOT_API_ORIGIN=https://app.example.com npm run build
const API_ORIGIN = process.env.JOBBOT_API_ORIGIN || "http://localhost:8000";

// Excluded on principle: automating LinkedIn applications violates its User
// Agreement and is aggressively fingerprinted/blocked. Never add it here.
const EXCLUDED_MATCHES = ["*://*.linkedin.com/*"];

export default defineManifest({
  manifest_version: 3,
  name: "JobBot Copilot",
  version: pkg.version,
  description:
    "Detects job postings on any careers page, autofills applications with your tailored resume, and tracks every application in your JobBot account. Review and submit yourself.",
  action: { default_popup: "src/popup/index.html", default_title: "JobBot Copilot" },
  options_ui: { page: "src/options/index.html", open_in_tab: true },
  background: { service_worker: "src/background/index.ts", type: "module" },
  permissions: ["storage"],
  host_permissions: [`${API_ORIGIN}/*`],
  content_scripts: [
    {
      // Runs on every page and every frame (like BidHub) so custom-domain
      // career pages, iframe-embedded ATS widgets (common for Greenhouse/
      // Workday embeds), and platforms outside the named list still get
      // detected. The script is inert everywhere else: `detectJob()` bails
      // out unless it finds a real job-posting signal, so nothing renders on
      // non-job pages or non-job frames.
      matches: ["<all_urls>"],
      exclude_matches: EXCLUDED_MATCHES,
      js: ["src/content/index.tsx"],
      run_at: "document_idle",
      all_frames: true,
    },
  ],
  web_accessible_resources: [
    { resources: ["assets/*"], matches: ["<all_urls>"] },
  ],
});
