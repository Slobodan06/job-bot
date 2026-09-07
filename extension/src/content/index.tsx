import { StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";

import { watchForJob } from "../detectors";
import type { BgToFrame, FrameToBg } from "../lib/frames";
import type { DetectedJob } from "../lib/types";
import { runFillInThisFrame } from "./fill-runner";
import { Overlay } from "./Overlay";

const isTopFrame = window.top === window.self;

function report(msg: FrameToBg): void {
  chrome.runtime.sendMessage(msg).catch(() => {
    /* background may not be ready yet (extension just installed/reloaded) */
  });
}

// Every frame (top and any iframe) independently detects and reports its own
// job signal, and independently fills itself when told to — a job posting or
// its application form frequently lives in an iframe, so no frame can assume
// it owns the whole picture.
watchForJob((job) => report({ type: "frame:report-job", job }));

chrome.runtime.onMessage.addListener((msg: BgToFrame) => {
  if (msg.type === "do-fill") {
    runFillInThisFrame(msg.job, msg.variant, msg.resumeVariantId).then((result) => {
      report({ type: "frame:fill-result", ...result });
    });
  }
});

// The user submitting the site's own form is detected locally, in whichever
// frame actually contains the form — a cross-origin iframe's clicks/submits
// never bubble up to the parent document, so this cannot be top-frame-only.
let submittedOnce = false;
const onSubmitSignal = () => {
  if (submittedOnce) return;
  submittedOnce = true;
  report({ type: "frame:submitted" });
};
document.addEventListener("submit", onSubmitSignal, true);
document.addEventListener(
  "click",
  (e) => {
    const target = e.target as HTMLElement;
    if (target.closest('button[type="submit"], input[type="submit"], [class*="submit" i]')) {
      setTimeout(onSubmitSignal, 400);
    }
  },
  true,
);

if (isTopFrame) {
  let host: HTMLDivElement | null = null;
  let root: Root | null = null;
  const dismissed = new Set<string>();

  const unmount = () => {
    root?.unmount();
    root = null;
    host?.remove();
    host = null;
  };

  const render = (job: DetectedJob) => {
    if (dismissed.has(job.url)) return;
    if (!host) {
      host = document.createElement("div");
      host.id = "jobbot-copilot-root";
      document.documentElement.appendChild(host);
      const shadow = host.attachShadow({ mode: "open" });
      const mountPoint = document.createElement("div");
      shadow.appendChild(mountPoint);
      root = createRoot(mountPoint);
    }
    root!.render(
      <StrictMode>
        <Overlay
          job={job}
          onDismiss={() => {
            dismissed.add(job.url);
            unmount();
          }}
        />
      </StrictMode>,
    );
  };

  chrome.runtime.onMessage.addListener((msg: BgToFrame) => {
    if (msg.type === "job:update") {
      if (msg.job) render(msg.job);
      else unmount();
    }
  });
}
