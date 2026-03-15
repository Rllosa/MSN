import { useEffect, useRef, useState } from "react";
import { ConversationDetail } from "../api/conversations";
import PlatformBadge from "./PlatformBadge";

interface Props {
  conversation: ConversationDetail;
  aptLabel?: string;
  onSwitchConversation?: (id: string) => void;
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatDateSeparator(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const diffDays = Math.floor((now.getTime() - d.getTime()) / (1000 * 60 * 60 * 24));
  if (diffDays === 0) return "Today";
  if (diffDays === 1) return "Yesterday";
  return d.toLocaleDateString([], {
    weekday: "long",
    month: "long",
    day: "numeric",
  });
}

function isSameDay(a: string, b: string): boolean {
  return new Date(a).toDateString() === new Date(b).toDateString();
}

interface ParsedBody {
  text: string;
  images: string[];
}

// Extract <img src="..."> URLs and strip all HTML tags from message body
function parseBody(raw: string): ParsedBody {
  const images: string[] = [];
  const imgRegex = /<img[^>]+src="([^"]+)"/gi;
  let match;
  while ((match = imgRegex.exec(raw)) !== null) {
    images.push(match[1]);
  }
  const text = raw.replace(/<[^>]+>/g, "").trim();
  return { text, images };
}

function ImageAttachment({ src }: { src: string }) {
  const [errored, setErrored] = useState(false);

  if (errored) {
    return (
      <div className="flex items-center gap-2 rounded-lg px-3 py-2 mb-1 bg-white/5 text-zinc-500 text-xs">
        <svg
          className="w-4 h-4 shrink-0"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={1.5}
            d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14M14 8h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"
          />
        </svg>
        Image expired
      </div>
    );
  }

  return (
    <a href={src} target="_blank" rel="noreferrer">
      <img
        src={src}
        alt="attachment"
        className="rounded-lg max-w-full mb-1"
        style={{ maxHeight: 200 }}
        onError={() => setErrored(true)}
      />
    </a>
  );
}

const PLATFORM_SWITCH_STYLE: Record<string, { bg: string; label: string; icon: JSX.Element }> = {
  whatsapp: {
    bg: "bg-[#25D366]",
    label: "WhatsApp",
    icon: (
      <svg viewBox="0 0 24 24" className="w-5 h-5 fill-white">
        <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347z" />
        <path d="M12 0C5.373 0 0 5.373 0 12c0 2.123.554 4.118 1.528 5.845L.057 23.571a.75.75 0 0 0 .92.921l5.763-1.47A11.95 11.95 0 0 0 12 24c6.627 0 12-5.373 12-12S18.627 0 12 0zm0 22c-1.891 0-3.666-.5-5.201-1.375l-.374-.217-3.876.988.999-3.774-.234-.389A9.96 9.96 0 0 1 2 12C2 6.477 6.477 2 12 2s10 4.477 10 10-4.477 10-10 10z" />
      </svg>
    ),
  },
  airbnb: {
    bg: "bg-[#FF5A5F]",
    label: "Airbnb",
    icon: (
      <svg viewBox="0 0 24 24" className="w-5 h-5 fill-white">
        <path d="M12 0C5.372 0 0 5.373 0 12s5.372 12 12 12 12-5.373 12-12S18.628 0 12 0zm5.369 17.368c-.372.901-1.088 1.559-2.01 1.855-.224.072-.453.107-.681.107-.672 0-1.336-.268-1.992-.801-.391.319-.788.554-1.184.7a3.123 3.123 0 0 1-1.049.18c-.908 0-1.731-.413-2.296-1.073-.574-.672-.819-1.574-.679-2.479.063-.4.198-.783.4-1.14l3.07-5.316c.159-.275.341-.535.546-.778.204-.243.43-.462.672-.654.241-.192.501-.357.774-.491A4.034 4.034 0 0 1 14 7.2c.314 0 .624.041.923.124.299.083.583.206.847.367.264.161.506.358.719.587.213.229.397.485.547.762l3.07 5.316c.405.701.542 1.521.38 2.318a3.12 3.12 0 0 1-.117.694zM14 8.8a2.4 2.4 0 1 0 0 4.8 2.4 2.4 0 0 0 0-4.8z" />
      </svg>
    ),
  },
  booking: {
    bg: "bg-[#003580]",
    label: "Booking",
    icon: (
      <svg viewBox="0 0 24 24" className="w-5 h-5 fill-white">
        <path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm1 17H7v-2h6v2zm0-4H7v-2h6v2zm0-4H7V7h6v2zm3 8h-2V7h2v10z" />
      </svg>
    ),
  },
};

export default function MessageThread({ conversation, aptLabel, onSwitchConversation }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [conversation.id, conversation.messages.length]);

  return (
    <div className="flex flex-col flex-1 min-h-0 bg-[#0f0f0f]">
      {/* Header */}
      <div className="px-6 py-4 bg-[#1a1a1a] border-b border-white/10 shrink-0 relative">
        {conversation.linked_conversation_id && onSwitchConversation && (() => {
          const targetPlatform = conversation.platform === "whatsapp" ? "booking" : "whatsapp";
          const style = PLATFORM_SWITCH_STYLE[targetPlatform] ?? PLATFORM_SWITCH_STYLE.whatsapp;
          const hasUnread = (conversation.linked_conversation_unread ?? 0) > 0;
          return (
            <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
              <div className="relative pointer-events-auto">
                <button
                  onClick={() => onSwitchConversation(conversation.linked_conversation_id!)}
                  className={`flex items-center gap-2 px-5 py-2 rounded-full text-sm font-semibold text-white transition-opacity hover:opacity-80 ${style.bg}`}
                  title={`Switch to ${style.label} thread`}
                >
                  {style.icon}
                  {style.label} thread
                </button>
                {hasUnread && (
                  <span className="absolute -top-1 -right-1 min-w-[18px] h-[18px] bg-red-500 text-white text-[10px] font-bold rounded-full flex items-center justify-center px-1">
                    {conversation.linked_conversation_unread}
                  </span>
                )}
              </div>
            </div>
          );
        })()}
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-full bg-zinc-700 text-white flex items-center justify-center font-bold text-sm shrink-0">
            {conversation.guest_name.charAt(0).toUpperCase()}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="font-semibold text-white text-sm">
                {conversation.guest_name}
              </h2>
              <PlatformBadge platform={conversation.platform} />
              {conversation.guest_contact?.endsWith("@reply.airbnb.com") && (
                <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400">
                  Inquiry
                </span>
              )}
              {conversation.guest_contact && (
                <span className="text-[10px] text-zinc-500 font-mono">
                  {conversation.guest_contact}
                </span>
              )}
            </div>
            {conversation.property_name && (
              <p className="text-xs text-zinc-500 truncate">
                {conversation.property_name}
                {aptLabel && <span className="text-zinc-600 ml-1">({aptLabel})</span>}
              </p>
            )}
          </div>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-6">
        {conversation.messages.length === 0 ? (
          <div className="flex items-center justify-center h-full text-sm text-zinc-600">
            No messages yet
          </div>
        ) : (
          conversation.messages.map((msg, i) => {
            const isOutbound = msg.direction === "outbound";
            const prevMsg = conversation.messages[i - 1];
            const showDate = i === 0 || !isSameDay(msg.sent_at, prevMsg.sent_at);
            const { text, images } = parseBody(msg.body);

            return (
              <div key={msg.id}>
                {showDate && (
                  <div className="flex items-center gap-3 my-5">
                    <div className="flex-1 h-px bg-white/10" />
                    <span className="text-xs text-zinc-500 font-medium shrink-0">
                      {formatDateSeparator(msg.sent_at)}
                    </span>
                    <div className="flex-1 h-px bg-white/10" />
                  </div>
                )}
                <div
                  className={`flex items-end gap-2 mb-2 ${isOutbound ? "flex-row-reverse" : "flex-row"}`}
                >
                  <div
                    className={`max-w-[70%] flex flex-col ${isOutbound ? "items-end" : "items-start"}`}
                  >
                    <div
                      className={`rounded-2xl px-4 py-2.5 text-sm leading-relaxed overflow-hidden ${
                        isOutbound
                          ? "bg-[#1a3a6b] text-white rounded-br-sm"
                          : "bg-[#2c2c2e] text-white rounded-bl-sm"
                      }`}
                    >
                      {images.map((src, idx) => (
                        <ImageAttachment key={idx} src={src} />
                      ))}
                      {text && <p className="whitespace-pre-wrap break-all">{text}</p>}
                    </div>
                    <span className="text-[10px] mt-1 text-zinc-600">
                      {formatTime(msg.sent_at)}
                    </span>
                  </div>
                </div>
              </div>
            );
          })
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
