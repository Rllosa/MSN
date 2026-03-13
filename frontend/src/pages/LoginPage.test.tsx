import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as authApi from "../api/auth";
import { useAuthStore } from "../store/auth";
import LoginPage from "./LoginPage";

// Reset auth store and mocks before each test
beforeEach(() => {
  useAuthStore.setState({ accessToken: null });
  vi.restoreAllMocks();
});

function renderLogin() {
  return render(
    <MemoryRouter>
      <LoginPage />
    </MemoryRouter>,
  );
}

describe("LoginPage", () => {
  it("shows error message on invalid credentials", async () => {
    vi.spyOn(authApi, "postLogin").mockRejectedValue(
      Object.assign(new Error("401"), { response: { status: 401 } }),
    );

    renderLogin();

    await userEvent.type(screen.getByLabelText("Email"), "bad@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "wrongpass");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

    expect(
      await screen.findByRole("alert"),
    ).toHaveTextContent("Invalid email or password.");
  });

  it("shows loading state while submitting", async () => {
    // Never resolves — keeps the button in loading state
    vi.spyOn(authApi, "postLogin").mockReturnValue(new Promise(() => {}));

    renderLogin();

    await userEvent.type(screen.getByLabelText("Email"), "user@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "password123");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

    expect(screen.getByRole("button", { name: /signing in/i })).toBeDisabled();
  });

  it("stores token and redirects on successful login", async () => {
    vi.spyOn(authApi, "postLogin").mockResolvedValue({
      access_token: "tok-abc",
    });

    renderLogin();

    await userEvent.type(screen.getByLabelText("Email"), "user@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "password123");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(useAuthStore.getState().accessToken).toBe("tok-abc");
    });
    // Token in store confirms login succeeded; navigation is handled by react-router
    // and tested at App level
  });
});
