import { Viewer, Worker } from "@react-pdf-viewer/core";
import "@react-pdf-viewer/core/lib/styles/index.css";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.js?url";

type Props = {
  fileUrl: string;
};

/**
 * Renders only the PDF pages (via PDF.js) — no browser PDF chrome, thumbnails, or side panes.
 */
export function UploadedPdfPreview({ fileUrl }: Props) {
  return (
    <Worker workerUrl={workerUrl}>
      <div
        style={{
          height: "clamp(560px, 78dvh, min(920px, 92dvh))",
          overflow: "auto",
          background: "var(--mantine-color-dark-9)",
        }}
      >
        <Viewer fileUrl={fileUrl} />
      </div>
    </Worker>
  );
}
