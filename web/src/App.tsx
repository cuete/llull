import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { FC } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Header } from "./components/Header";
import { LogsDrawer } from "./components/LogsDrawer";
import { useConsoleLogs } from "./hooks/useConsoleLogs";
import { SettingsPage } from "./features/settings/SettingsPage";
import { TopicList } from "./features/topics/TopicList";
import { TopicView } from "./features/topics/TopicView";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

export const App: FC = () => {
  // Initialize console log capture app-wide
  useConsoleLogs();

  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <div style={{ display: "flex", flexDirection: "column", minHeight: "100vh" }}>
          <Header />
          <main style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
            <Routes>
              <Route path="/" element={<TopicList />} />
              <Route path="/topics/:id" element={<TopicView />} />
              <Route path="/settings" element={<SettingsPage />} />
            </Routes>
          </main>
          <LogsDrawer />
        </div>
      </BrowserRouter>
    </QueryClientProvider>
  );
};
