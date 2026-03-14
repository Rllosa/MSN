import { useNavigate } from "react-router-dom";
import { ConversationSummary } from "../api/conversations";
import ConversationItem from "./ConversationItem";

interface Props {
  conversations: ConversationSummary[];
  selectedId: string | null;
  hasMore: boolean;
  loadingMore: boolean;
  onLoadMore: () => void;
}

export default function ConversationList({
  conversations,
  selectedId,
  hasMore,
  loadingMore,
  onLoadMore,
}: Props) {
  const navigate = useNavigate();

  if (conversations.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-2 text-zinc-600">
        <svg
          className="w-10 h-10 opacity-40"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={1.5}
            d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
          />
        </svg>
        <p className="text-sm">No conversations yet</p>
      </div>
    );
  }

  return (
    <div className="overflow-y-auto h-full">
      {conversations.map((conv) => (
        <ConversationItem
          key={conv.id}
          conv={conv}
          selected={conv.id === selectedId}
          onClick={() => navigate(`/inbox/${conv.id}`)}
        />
      ))}
      {hasMore && (
        <div className="p-4 flex justify-center">
          <button
            onClick={onLoadMore}
            disabled={loadingMore}
            className="text-sm text-blue-400 hover:text-blue-300 font-medium disabled:opacity-50 transition-colors"
          >
            {loadingMore ? "Loading…" : "Load more"}
          </button>
        </div>
      )}
    </div>
  );
}
