import client from "./client";

export interface ConversationSummary {
  id: string;
  platform: string;
  guest_name: string;
  guest_contact: string | null;
  property_id: string | null;
  property_name: string | null;
  status: string;
  unread_count: number;
  last_message_at: string | null;
  created_at: string;
  linked_whatsapp_unread: number | null;
}

export interface MessageOut {
  id: string;
  direction: string; // "inbound" | "outbound"
  body: string;
  sent_at: string;
  created_at: string;
}

export interface ConversationDetail extends ConversationSummary {
  messages: MessageOut[];
  linked_conversation_id: string | null;
  linked_conversation_unread: number | null;
}

export interface ConversationsPage {
  items: ConversationSummary[];
  total: number;
  limit: number;
  offset: number;
}

export async function getConversations(
  offset = 0,
  limit = 20,
  unreadOnly = false,
  search = "",
  platforms: string[] = [],
  propertyIds: string[] = [],
): Promise<ConversationsPage> {
  const res = await client.get<ConversationsPage>("/conversations/", {
    params: {
      offset,
      limit,
      ...(unreadOnly ? { unread_only: true } : {}),
      ...(search ? { search } : {}),
      ...(platforms.length > 0 ? { platform: platforms.join(",") } : {}),
      ...(propertyIds.length > 0 ? { property_id: propertyIds.join(",") } : {}),
    },
  });
  return res.data;
}

export async function getConversation(id: string): Promise<ConversationDetail> {
  const res = await client.get<ConversationDetail>(`/conversations/${id}`);
  return res.data;
}

export async function markConversationRead(id: string): Promise<void> {
  await client.patch(`/conversations/${id}`, { mark_read: true });
}

export async function postReply(convId: string, content: string): Promise<MessageOut> {
  const res = await client.post<MessageOut>(`/conversations/${convId}/reply`, {
    content,
  });
  return res.data;
}
