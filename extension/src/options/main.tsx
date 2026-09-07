import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { WEB_ORIGIN } from "../lib/env";

function Options() {
  return (
    <StrictMode>
      <h1>JobBot Copilot</h1>
      <p>
        Your autofill profile (contact details, work authorization, EEO answers, and
        custom Q&amp;A) lives in your JobBot account so the web app and the extension
        stay in sync.
      </p>
      <p>
        <a href={`${WEB_ORIGIN}/applications`} target="_blank" rel="noreferrer">
          Autofill setup: base resume &amp; profile →
        </a>
      </p>
      <hr />
      <p style={{ color: "#666" }}>
        JobBot Copilot never submits an application for you and does not run on
        LinkedIn. Always review AI-drafted answers before submitting.
      </p>
    </StrictMode>
  );
}

createRoot(document.getElementById("root")!).render(<Options />);
