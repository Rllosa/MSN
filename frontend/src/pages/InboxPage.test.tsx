import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as convsApi from "../api/conversations";
import InboxPage from "./InboxPage";

vi.mock("../api/conversations", () => ({
  getConversations: vi.fn(),
  getConversation: vi.fn(),
  markConversationRead: vi.fn(),
}));

const CONV_1 = {
  id: "conv-1",
  platform: "airbnb",
  guest_name: "Alice",
  guest_contact: null,
  property_id: "prop-1",
  property_name: "Apt3",
  status: "active",
  unread_count: 2,
  last_message_at: "2024-06-01T10:00:00Z",
  created_at: "2024-06-01T09:00:00Z",
  linked_whatsapp_unread: null,
};

const DETAIL_1 = {
  ...CONV_1,
  messages: [
    {
      id: "msg-1",
      direction: "inbound",
      body: "Hello, is the place available?",
      sent_at: "2024-06-01T10:00:00Z",
      created_at: "2024-06-01T10:00:00Z",
    },
  ],
  linked_conversation_id: null,
  linked_conversation_unread: null,
};

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(convsApi.markConversationRead).mockResolvedValue(undefined);
});

function renderInbox(initialPath = "/inbox") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/inbox" element={<InboxPage />} />
        <Route path="/inbox/:conversationId" element={<InboxPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("InboxPage", () => {
  it("renders conversation list from API", async () => {
    vi.mocked(convsApi.getConversations).mockResolvedValue({
      items: [CONV_1],
      total: 1,
      limit: 20,
      offset: 0,
    });

    renderInbox();

    await waitFor(() => {
      expect(screen.getByText("Alice")).toBeInTheDocument();
    });
    expect(screen.getByText("Apt3")).toBeInTheDocument();
  });

  it("renders message thread when conversation is selected", async () => {
    vi.mocked(convsApi.getConversations).mockResolvedValue({
      items: [CONV_1],
      total: 1,
      limit: 20,
      offset: 0,
    });
    vi.mocked(convsApi.getConversation).mockResolvedValue(DETAIL_1);

    renderInbox("/inbox/conv-1");

    await waitFor(() => {
      expect(screen.getByText("Hello, is the place available?")).toBeInTheDocument();
    });
  });

  it("calls markConversationRead when opening a conversation with unread messages", async () => {
    vi.mocked(convsApi.getConversations).mockResolvedValue({
      items: [CONV_1],
      total: 1,
      limit: 20,
      offset: 0,
    });
    vi.mocked(convsApi.getConversation).mockResolvedValue(DETAIL_1);

    renderInbox("/inbox/conv-1");

    await waitFor(() => {
      expect(convsApi.markConversationRead).toHaveBeenCalledWith("conv-1");
    });
  });
});
