import "@fontsource/doto/700.css";
import "@fontsource/doto/900.css";
import "./styles.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { ToastProvider } from "./components/feedback";

const client = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 15_000, refetchOnWindowFocus: true, retry: 1 },
  },
});

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <StrictMode>
      <QueryClientProvider client={client}>
        <ToastProvider>
          <App />
        </ToastProvider>
      </QueryClientProvider>
    </StrictMode>,
  );
}
