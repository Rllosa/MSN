import { ConversationSummary } from "../api/conversations";
import PlatformBadge from "./PlatformBadge";
import PlatformIcon from "./PlatformIcon";

interface Props {
  conv: ConversationSummary;
  selected: boolean;
  onClick: () => void;
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

export default function ConversationItem({ conv, selected, onClick }: Props) {
  return (
    <button
      onClick={onClick}
      className={`w-full text-left px-4 py-3.5 transition-colors border-b border-white/5 ${
        selected
          ? "bg-white/10 border-l-[3px] border-l-blue-500"
          : "border-l-[3px] border-l-transparent hover:bg-white/5"
      }`}
    >
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
          {conv.unread_count > 0 && (
            <span className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full bg-blue-600 text-white text-[10px] font-bold">
              {conv.unread_count > 99 ? "99+" : conv.unread_count}
            </span>
          )}
        </div>
      </div>
      <div className="flex items-center gap-2 pl-[42px]">
        <PlatformBadge platform={conv.platform} />
        {conv.guest_contact?.endsWith("@reply.airbnb.com") && (
          <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 shrink-0">
            Inquiry
          </span>
        )}
        {conv.property_name && (
          <span className="text-xs text-zinc-500 truncate">{conv.property_name}</span>
        )}
      </div>
    </button>
  );
}
