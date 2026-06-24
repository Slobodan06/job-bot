import { MantineProvider, createTheme, rem } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "@mantine/core/styles.css";
import "@mantine/dropzone/styles.css";
import "@mantine/notifications/styles.css";
import "./index.css";

const theme = createTheme({
  fontFamily: '"DM Sans", system-ui, -apple-system, sans-serif',
  fontFamilyMonospace: '"JetBrains Mono", ui-monospace, monospace',
  headings: {
    fontFamily: '"DM Sans", system-ui, -apple-system, sans-serif',
    fontWeight: "600",
  },
  defaultRadius: "md",
  primaryColor: "teal",
  breakpoints: {
    xs: "30em",
    sm: "48em",
    md: "62em",
    lg: "75em",
    xl: "90em",
  },
  spacing: {
    xs: rem(8),
    sm: rem(12),
    md: rem(16),
    lg: rem(24),
    xl: rem(32),
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MantineProvider defaultColorScheme="dark" theme={theme}>
      <Notifications position="top-center" zIndex={10000} />
      <App />
    </MantineProvider>
  </StrictMode>,
);
