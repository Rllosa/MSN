import { useRef, useState } from "react";
import { postReply } from "../api/conversations";

interface Props {
  conversationId: string;
  onSent: () => void;
}

export default function ReplyComposer({ conversationId, onSent }: Props) {
  const [content, setContent] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const canSend = content.trim().length > 0 && !sending;

  const handleSend = async () => {
    if (!canSend) return;
    setSending(true);
    setError(null);
    try {
      await postReply(conversationId, content.trim());
      setContent("");
      onSent();
    } catch {
      setError("Failed to send. Please try again.");
    } finally {
      setSending(false);
      textareaRef.current?.focus();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="shrink-0 border-t border-white/10 bg-[#1a1a1a] px-4 py-3">
      {error && <p className="text-xs text-red-400 mb-2 px-1">{error}</p>}
      <div className="flex items-end gap-2">
        <textarea
          ref={textareaRef}
          value={content}
          onChange={(e) => setContent(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Write a reply… (⌘↵ to send)"
          rows={3}
          className="flex-1 resize-none bg-zinc-800 text-sm text-white placeholder-zinc-500 rounded-xl px-3 py-2.5 outline-none focus:ring-1 focus:ring-blue-600 leading-relaxed"
        />
        <button
          onClick={handleSend}
          disabled={!canSend}
          className="shrink-0 flex items-center justify-center w-9 h-9 rounded-xl bg-blue-600 text-white disabled:opacity-40 disabled:cursor-not-allowed hover:bg-blue-500 transition-colors"
          title="Send (⌘↵)"
        >
          {sending ? (
            <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle
                className="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                strokeWidth="4"
              />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8v8H4z"
              />
            </svg>
          ) : (
            <svg
              className="w-4 h-4 translate-x-px"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"
              />
            </svg>
          )}
        </button>
      </div>
    </div>
  );
}
