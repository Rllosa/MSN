import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as authApi from "./api/auth";
import App from "./App";
import { useAuthStore } from "./store/auth";

// Hoist mock so App.tsx receives the mocked binding at import time
vi.mock("./api/auth", () => ({
  postRefresh: vi.fn(),
  postLogin: vi.fn(),
  postLogout: vi.fn(),
}));

beforeEach(() => {
  useAuthStore.setState({ accessToken: null });
  vi.resetAllMocks();
  // BrowserRouter uses window.location; reset between tests so each starts at "/"
  window.history.pushState({}, "", "/");
});

describe("App", () => {
  it("shows login page when no session exists (silent refresh fails)", async () => {
    vi.mocked(authApi.postRefresh).mockRejectedValue(new Error("no session"));

    render(<App />);

    // After silent refresh fails, login form should appear
    expect(
      await screen.findByRole("button", { name: /sign in/i }),
    ).toBeInTheDocument();
  });

  it("shows inbox placeholder when session is restored (silent refresh succeeds)", async () => {
    vi.mocked(authApi.postRefresh).mockResolvedValue({
      access_token: "restored-tok",
    });

    render(<App />);

    await waitFor(() => {
      expect(
        screen.getByText("MSN — Unified Messaging Dashboard"),
      ).toBeInTheDocument();
    });
  });
});
