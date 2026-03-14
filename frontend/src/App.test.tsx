import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as authApi from "./api/auth";
import * as convsApi from "./api/conversations";
import App from "./App";
import { useAuthStore } from "./store/auth";

// Hoist mocks so all consumers receive mocked bindings at import time
vi.mock("./api/auth", () => ({
  postRefresh: vi.fn(),
  postLogin: vi.fn(),
  postLogout: vi.fn(),
}));

vi.mock("./api/conversations", () => ({
  getConversations: vi.fn(),
  getConversation: vi.fn(),
  markConversationRead: vi.fn(),
}));

beforeEach(() => {
  useAuthStore.setState({ accessToken: null });
  vi.resetAllMocks();
  // BrowserRouter uses window.location; reset between tests so each starts at "/"
  window.history.pushState({}, "", "/");
  // Default: empty inbox
  vi.mocked(convsApi.getConversations).mockResolvedValue({
    items: [],
    total: 0,
    limit: 20,
    offset: 0,
  });
});

describe("App", () => {
  it("shows login page when no session exists (silent refresh fails)", async () => {
    vi.mocked(authApi.postRefresh).mockRejectedValue(new Error("no session"));

    render(<App />);

    // After silent refresh fails, login form should appear
    expect(await screen.findByRole("button", { name: /sign in/i })).toBeInTheDocument();
  });

  it("shows inbox when session is restored (silent refresh succeeds)", async () => {
    vi.mocked(authApi.postRefresh).mockResolvedValue({
      access_token: "restored-tok",
    });

    render(<App />);

    await waitFor(() => {
      expect(screen.getByText("Inbox")).toBeInTheDocument();
    });
  });
});
