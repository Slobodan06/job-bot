import { deepQueryAll, deepText } from "./dom";
import type { DetectedJob } from "../lib/types";

const clip = (s: string, n: number) => (s || "").replace(/\s+\n/g, "\n").trim().slice(0, n);

// Cheap signals checked on every page before doing any real DOM scraping, since
// the content script now runs on <all_urls> (like BidHub) and must stay inert
// and inexpensive on the other 99% of pages a user visits.
const JOB_URL_HINT_RE = /\/(jobs?|careers?|positions?|openings?|vacanc\w*|postings?|apply)(?:[/?#]|$)/i;
const JOB_TITLE_HINT_RE = /\b(job|career|hiring|position|opening|vacancy|apply)\b/i;
const KNOWN_ATS_HOST_RE =
  /greenhouse\.io$|lever\.co$|myworkdayjobs\.com$|ashbyhq\.com$|smartrecruiters\.com$|workable\.com$|icims\.com$|bamboohr\.com$|jobvite\.com$|breezy\.hr$/i;

function looksLikeJobPage(): boolean {
  return (
    KNOWN_ATS_HOST_RE.test(location.hostname) ||
    JOB_URL_HINT_RE.test(location.pathname) ||
    JOB_TITLE_HINT_RE.test(document.title) ||
    !!document.querySelector('script[type="application/ld+json"]')
  );
}

function jsonLdJob(): Partial<DetectedJob> | null {
  // JSON-LD is virtually always in the light DOM, but pierce shadow roots too
  // in case a component library injects it (cheap: script tags are rare).
  for (const el of deepQueryAll('script[type="application/ld+json"]')) {
    try {
      const raw = JSON.parse(el.textContent || "");
      const nodes = Array.isArray(raw) ? raw : [raw, ...(raw["@graph"] || [])];
      for (const node of nodes) {
        if (node && node["@type"] === "JobPosting") {
          const org = node.hiringOrganization?.name || "";
          const loc =
            node.jobLocation?.address?.addressLocality ||
            node.jobLocation?.[0]?.address?.addressLocality ||
            node.jobLocation?.address?.addressRegion ||
            "";
          const desc = typeof node.description === "string"
            ? node.description.replace(/<[^>]+>/g, " ")
            : "";
          return {
            company: clip(org, 200),
            job_title: clip(node.title || "", 300),
            location: clip(loc, 200),
            text: clip(desc, 40000),
          };
        }
      }
    } catch {
      /* ignore */
    }
  }
  return null;
}

function bySelectors(sel: {
  title?: string;
  company?: string;
  location?: string;
  body?: string;
}): Partial<DetectedJob> {
  // deepText pierces open shadow roots, which is required for Workday's and
  // several other ATS's web-component-based candidate experience.
  const pick = (s?: string) => (s ? clip(deepText(s), 40000) : "");
  return {
    job_title: pick(sel.title).slice(0, 300),
    company: pick(sel.company).slice(0, 200),
    location: pick(sel.location).slice(0, 200),
    text: pick(sel.body),
  };
}

// Ordered (host regex, ats name, selectors). First match wins; everything else
// falls through to the generic selector set below.
const ATS_DETECTORS: Array<{
  host: RegExp;
  ats: string;
  sel: Parameters<typeof bySelectors>[0];
}> = [
  {
    host: /greenhouse\.io$/i,
    ats: "greenhouse",
    sel: {
      title: "h1.app-title, .job__title h1, [class*='JobTitle'], h1",
      company: ".company-name, .app-title + .company-name",
      location: ".location, .job__location, [class*='JobLocation']",
      body: "#content, #job_description, .job__description, [class*='JobDescription'], .body",
    },
  },
  {
    host: /lever\.co$/i,
    ats: "lever",
    sel: {
      title: ".posting-headline h2, [data-qa='posting-name'], h2",
      location: ".posting-categories .location, [data-qa='posting-location'], .location",
      body: ".posting-page, [data-qa='job-description'], .section-wrapper.page-full-width, .content",
    },
  },
  {
    host: /myworkdayjobs\.com$/i,
    ats: "workday",
    sel: {
      // Workday's Candidate Experience renders behind several template
      // variants across tenants, and often inside open shadow roots — these
      // data-automation-id values are the most stable anchors across them.
      title: '[data-automation-id="jobPostingHeader"], [data-automation-id="jobTitle"], h1, h2',
      location:
        '[data-automation-id="locations"], [data-automation-id="jobPostingLocation"], [data-automation-id="subtitle"], [data-automation-id="jobPostingSubtitle"]',
      body:
        '[data-automation-id="jobPostingDescription"], [data-automation-id="job-posting-description"], [data-automation-id="richText"], main',
    },
  },
  {
    host: /ashbyhq\.com$/i,
    ats: "ashby",
    sel: { title: "h1", body: '[class*="_description"], main' },
  },
  {
    host: /smartrecruiters\.com$/i,
    ats: "smartrecruiters",
    sel: {
      title: "h1, .job-title",
      company: ".company-name",
      location: ".job-location, [class*='location']",
      body: "#st-jobDescription, .job-sections, main",
    },
  },
  {
    host: /workable\.com$/i,
    ats: "workable",
    sel: {
      title: "h1, [data-ui='job-title']",
      location: "[data-ui='job-location']",
      body: "[data-ui='job-description'], section",
    },
  },
  {
    host: /icims\.com$/i,
    ats: "icims",
    sel: {
      title: ".iCIMS_Header, h1",
      location: ".iCIMS_JobHeaderLocation",
      body: "#iCIMS_JobContent, .iCIMS_InfoMsg_Text, main",
    },
  },
  {
    host: /bamboohr\.com$/i,
    ats: "bamboohr",
    sel: { title: "h1, .BambooHR-ATS-Jobs-Item", body: "#BambooHR-ATS-Job, main" },
  },
  {
    host: /jobvite\.com$/i,
    ats: "jobvite",
    sel: { title: "h1, .jv-job-detail-title", location: ".jv-job-detail-meta", body: ".jv-job-detail-description, main" },
  },
  {
    host: /breezy\.hr$/i,
    ats: "breezy",
    sel: { title: "h1, .position-header h1", body: ".position-description, main" },
  },
];

const GENERIC_SEL: Parameters<typeof bySelectors>[0] = {
  title: "h1",
  body: "main, article, #content, #job-description, [class*='job-description'], [class*='JobDescription'], body",
};

function detectHost(): { ats: string; data: Partial<DetectedJob> } {
  const host = location.hostname;
  const match = ATS_DETECTORS.find((d) => d.host.test(host));
  if (match) return { ats: match.ats, data: bySelectors(match.sel) };
  return { ats: "other", data: bySelectors(GENERIC_SEL) };
}

export function detectJob(): DetectedJob | null {
  if (!looksLikeJobPage()) return null;

  const { ats, data } = detectHost();
  const ld = jsonLdJob() || {};
  const metaTitle =
    (document.querySelector('meta[property="og:title"]') as HTMLMetaElement | null)?.content || "";
  const job: DetectedJob = {
    url: location.href,
    page_title: clip(document.title, 500),
    ats,
    company: ld.company || data.company || "",
    job_title: ld.job_title || data.job_title || clip(metaTitle, 300),
    location: ld.location || data.location || "",
    text: (ld.text && ld.text.length > (data.text || "").length ? ld.text : data.text) || "",
  };
  // Require a plausible posting: real body text or a JSON-LD JobPosting. On a
  // known ATS host we already trust the domain, so accept a shorter snippet
  // (some apply-flow shells stream content in progressively).
  const minLength = KNOWN_ATS_HOST_RE.test(location.hostname) ? 60 : 200;
  if (job.text.length < minLength && !ld.job_title) return null;
  return job;
}

/** Fire `cb` on first load and on SPA navigations (history + DOM), debounced. */
export function watchForJob(cb: (job: DetectedJob | null) => void): () => void {
  let last = "";
  let timer: number | undefined;
  const run = () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => {
      // Cheap gate first: on the vast majority of pages (mail, docs, feeds)
      // this bails before touching the DOM in any expensive way.
      if (!looksLikeJobPage()) {
        if (last) {
          last = "";
          cb(null);
        }
        return;
      }
      const job = detectJob();
      const sig = job ? job.url + "|" + job.job_title : "";
      if (sig !== last) {
        last = sig;
        cb(job);
      }
    }, 700);
  };
  const origPush = history.pushState;
  const origReplace = history.replaceState;
  history.pushState = function (...args) {
    origPush.apply(this, args as never);
    run();
  };
  history.replaceState = function (...args) {
    origReplace.apply(this, args as never);
    run();
  };
  window.addEventListener("popstate", run);
  // childList/subtree only (no attributes/characterData) keeps this cheap even
  // on pages with heavy, unrelated DOM churn.
  const mo = new MutationObserver(run);
  mo.observe(document.documentElement, { childList: true, subtree: true });
  run();
  return () => {
    history.pushState = origPush;
    history.replaceState = origReplace;
    window.removeEventListener("popstate", run);
    mo.disconnect();
    window.clearTimeout(timer);
  };
}
