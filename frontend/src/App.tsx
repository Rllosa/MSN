import { useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { postRefresh } from "./api/auth";
import RequireAuth from "./components/RequireAuth";
import LoginPage from "./pages/LoginPage";
import { useAuthStore } from "./store/auth";

// TODO(SOLO-115): replace with real inbox view
function InboxPlaceholder() {
  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <h1 className="text-2xl font-semibold text-gray-800">
        MSN — Unified Messaging Dashboard
      </h1>
    </div>
  );
}

export default function App() {
  const setToken = useAuthStore((s) => s.setToken);
  // null = checking session, false = no session
  const [authReady, setAuthReady] = useState<boolean | null>(null);

  useEffect(() => {
    // Silent refresh on mount — keeps users logged in across page reloads
    postRefresh()
      .then(({ access_token }) => {
        setToken(access_token);
        setAuthReady(true);
      })
      .catch(() => {
        setAuthReady(false);
      });
  }, [setToken]);

  // Hold render until we know whether a session exists — prevents flash of /login
  if (authReady === null) {
    return null;
  }

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<RequireAuth />}>
          <Route path="/" element={<InboxPlaceholder />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
