import { ConversationSummary } from "../api/conversations";
import PlatformBadge from "./PlatformBadge";
import PlatformIcon from "./PlatformIcon";

interface Props {
  conv: ConversationSummary;
  selected: boolean;
  onClick: () => void;
  onArchive?: (id: string, archive: boolean) => void;
}

function formatLabel(iso: string | null): {
  primary: string;
  secondary: string | null;
} {
  if (!iso) return { primary: "", secondary: null };
  const d = new Date(iso);
  const now = new Date();

  const isToday = d.toDateString() === now.toDateString();
  const isWithin3Days = now.getTime() - d.getTime() < 3 * 24 * 60 * 60 * 1000;
  const timeStr = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  if (isToday) return { primary: timeStr, secondary: null };
  if (isWithin3Days)
    return {
      primary: d.toLocaleDateString([], { weekday: "short" }),
      secondary: timeStr,
    };
  return {
    primary: d.toLocaleDateString([], { month: "short", day: "numeric" }),
    secondary: timeStr,
  };
}

export default function ConversationItem({
  conv,
  selected,
  onClick,
  onArchive,
}: Props) {
  const isArchived = conv.status === "archived";

  return (
    <div
      className={`group relative w-full border-b border-white/5 ${
        selected
          ? "bg-white/10 border-l-[3px] border-l-blue-500"
          : "border-l-[3px] border-l-transparent hover:bg-white/5"
      }`}
    >
      <button onClick={onClick} className="w-full text-left px-4 py-3.5">
        <div className="flex items-start justify-between gap-2 mb-1.5">
          <div className="flex items-center gap-2.5 min-w-0">
            <PlatformIcon platform={conv.platform} />
            <div className="min-w-0">
              <span
                className={`text-sm truncate block leading-tight ${
                  conv.unread_count > 0
                    ? "font-bold text-white"
                    : "font-medium text-zinc-300"
                }`}
              >
                {conv.guest_name}
              </span>
              {conv.guest_contact && (
                <span className="text-[10px] text-zinc-600 font-mono leading-tight">
                  {conv.guest_contact}
                </span>
              )}
            </div>
          </div>
          <div className="flex flex-col items-end gap-1 shrink-0">
            {(() => {
              const { primary, secondary } = formatLabel(conv.last_message_at);
              return (
                <div className="flex flex-col items-end leading-tight">
                  <span className="text-[11px] text-zinc-400">{primary}</span>
                  {secondary && (
                    <span className="text-[11px] text-zinc-600">{secondary}</span>
                  )}
                </div>
              );
            })()}
            {(() => {
              const total = conv.unread_count + (conv.linked_whatsapp_unread ?? 0);
              return total > 0 ? (
                <span className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full bg-blue-600 text-white text-[10px] font-bold">
                  {total > 99 ? "99+" : total}
                </span>
              ) : null;
            })()}
          </div>
        </div>
        <div className="flex items-center gap-2 pl-[42px]">
          <PlatformBadge platform={conv.platform} />
          {conv.guest_contact?.endsWith("@reply.airbnb.com") && (
            <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 shrink-0">
              Inquiry
            </span>
          )}
          {conv.linked_whatsapp_unread !== null && (
            <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-[#25D366]/15 text-[#25D366] shrink-0">
              WhatsApp
            </span>
          )}
          {conv.property_name && (
            <span className="text-xs text-zinc-500 truncate">{conv.property_name}</span>
          )}
        </div>
      </button>
      {onArchive && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onArchive(conv.id, !isArchived);
          }}
          title={isArchived ? "Unarchive" : "Archive"}
          className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded hover:bg-white/10 text-zinc-500 hover:text-zinc-200"
        >
          {isArchived ? (
            /* Inbox / unarchive icon */
            <svg
              className="w-3.5 h-3.5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0H4m8-4v8"
              />
            </svg>
          ) : (
            /* Archive icon */
            <svg
              className="w-3.5 h-3.5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4"
              />
            </svg>
          )}
        </button>
      )}
    </div>
  );
}
