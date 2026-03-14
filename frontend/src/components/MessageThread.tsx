import { useEffect, useRef, useState } from "react";
import { ConversationDetail } from "../api/conversations";
import PlatformBadge from "./PlatformBadge";

interface Props {
  conversation: ConversationDetail;
  aptLabel?: string;
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

export default function MessageThread({ conversation, aptLabel }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [conversation.id, conversation.messages.length]);

  return (
    <div className="flex flex-col h-full bg-[#0f0f0f]">
      {/* Header */}
      <div className="px-6 py-4 bg-[#1a1a1a] border-b border-white/10 shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-full bg-zinc-700 text-white flex items-center justify-center font-bold text-sm shrink-0">
            {conversation.guest_name.charAt(0).toUpperCase()}
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
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
                {aptLabel && (
                  <span className="text-zinc-600 ml-1">({aptLabel})</span>
                )}
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
