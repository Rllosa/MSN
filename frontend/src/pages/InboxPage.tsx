import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useDeferredValue,
} from "react";
import { useParams, useSearchParams } from "react-router-dom";
import {
  ConversationDetail,
  ConversationSummary,
  getConversation,
  getConversations,
  markConversationRead,
} from "../api/conversations";
import { getProperties, Property } from "../api/properties";
import { useInboxSocket } from "../api/socket";
import FilterDropdown from "../components/FilterDropdown";
import ConversationList from "../components/ConversationList";
import MessageThread from "../components/MessageThread";

const PAGE_SIZE = 20;
const POLL_INTERVAL_MS = 30_000;

const PLATFORM_ITEMS = [
  { value: "airbnb", label: "Airbnb" },
  { value: "booking", label: "Booking.com" },
  { value: "whatsapp", label: "WhatsApp" },
];

export default function InboxPage() {
  const { conversationId } = useParams<{ conversationId?: string }>();
  const conversationIdRef = useRef(conversationId);
  conversationIdRef.current = conversationId;

  const [searchParams, setSearchParams] = useSearchParams();

  // URL-persisted filter params (strings used as effect deps to avoid
  // array identity churn on every render)
  const platformParam = searchParams.get("platform") ?? "";
  const propertyParam = searchParams.get("property") ?? "";

  const selectedPlatforms = useMemo(
    () => platformParam.split(",").filter(Boolean),
    [platformParam],
  );
  const selectedPropertyIds = useMemo(
    () => propertyParam.split(",").filter(Boolean),
    [propertyParam],
  );

  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loadingList, setLoadingList] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [searchInput, setSearchInput] = useState("");
  const search = useDeferredValue(searchInput);

  const [properties, setProperties] = useState<Property[]>([]);
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  // Refs for stale-closure-safe reads inside fetchList
  const unreadOnlyRef = useRef(unreadOnly);
  unreadOnlyRef.current = unreadOnly;
  const searchRef = useRef(search);
  searchRef.current = search;
  const selectedPlatformsRef = useRef(selectedPlatforms);
  selectedPlatformsRef.current = selectedPlatforms;
  const selectedPropertyIdsRef = useRef(selectedPropertyIds);
  selectedPropertyIdsRef.current = selectedPropertyIds;

  // Refresh the conversation list (replace = reset to page 1)
  const fetchList = useCallback(
    async (replace = true) => {
      const offset = replace ? 0 : conversations.length;
      const page = await getConversations(
        offset,
        PAGE_SIZE,
        unreadOnlyRef.current,
        searchRef.current,
        selectedPlatformsRef.current,
        selectedPropertyIdsRef.current,
      );
      setTotal(page.total);
      if (replace) {
        setConversations(page.items);
      } else {
        setConversations((prev) => [...prev, ...page.items]);
      }
    },
    [conversations.length],
  );

  // Silently refresh detail for the currently open conversation
  const refreshDetail = useCallback(async (convId: string) => {
    try {
      const d = await getConversation(convId);
      setDetail(d);
    } catch {
      // silently ignore — stale data is fine
    }
  }, []);

  // WebSocket: on new_message → refresh list + detail if it's the open conv
  useInboxSocket((convId) => {
    fetchList(true).catch(() => {});
    if (convId === conversationIdRef.current) {
      refreshDetail(convId).catch(() => {});
    }
  });

  // Initial load + fetch properties + window.focus refresh + 30s fallback polling
  useEffect(() => {
    setLoadingList(true);
    fetchList(true).finally(() => setLoadingList(false));
    getProperties()
      .then(setProperties)
      .catch(() => {});

    const onFocus = () => fetchList(true).catch(() => {});
    window.addEventListener("focus", onFocus);

    const interval = setInterval(
      () => fetchList(true).catch(() => {}),
      POLL_INTERVAL_MS,
    );

    return () => {
      window.removeEventListener("focus", onFocus);
      clearInterval(interval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-fetch when filters change
  useEffect(() => {
    setLoadingList(true);
    fetchList(true).finally(() => setLoadingList(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [unreadOnly, search, platformParam, propertyParam]);

  const handleLoadMore = async () => {
    setLoadingMore(true);
    await fetchList(false);
    setLoadingMore(false);
  };

  // Load detail when conversation selection changes
  useEffect(() => {
    if (!conversationId) {
      setDetail(null);
      return;
    }
    setLoadingDetail(true);
    getConversation(conversationId)
      .then((d) => {
        setDetail(d);
        if (d.unread_count > 0) {
          markConversationRead(conversationId).then(() => {
            setConversations((prev) =>
              prev.map((c) =>
                c.id === conversationId ? { ...c, unread_count: 0 } : c,
              ),
            );
          });
        }
      })
      .catch(() => setDetail(null))
      .finally(() => setLoadingDetail(false));
  }, [conversationId]);

  const togglePlatform = (p: string) => {
    const next = selectedPlatforms.includes(p)
      ? selectedPlatforms.filter((x) => x !== p)
      : [...selectedPlatforms, p];
    setSearchParams((prev) => {
      const params = new URLSearchParams(prev);
      if (next.length > 0) params.set("platform", next.join(","));
      else params.delete("platform");
      return params;
    });
  };

  const clearPlatforms = () => {
    setSearchParams((prev) => {
      const params = new URLSearchParams(prev);
      params.delete("platform");
      return params;
    });
  };

  const toggleProperty = (id: string) => {
    const next = selectedPropertyIds.includes(id)
      ? selectedPropertyIds.filter((x) => x !== id)
      : [...selectedPropertyIds, id];
    setSearchParams((prev) => {
      const params = new URLSearchParams(prev);
      if (next.length > 0) params.set("property", next.join(","));
      else params.delete("property");
      return params;
    });
  };

  const clearProperties = () => {
    setSearchParams((prev) => {
      const params = new URLSearchParams(prev);
      params.delete("property");
      return params;
    });
  };

  const propertyItems = useMemo(
    () => properties.map((p) => ({ value: p.id, label: p.name })),
    [properties],
  );

  const hasMore = conversations.length < total;

  return (
    <div className="flex h-screen bg-[#111111]">
      {/* Left pane */}
      <div className="w-80 shrink-0 bg-[#1a1a1a] border-r border-white/10 flex flex-col">
        <div className="px-5 py-4 border-b border-white/10">
          <div className="flex items-center justify-between mb-3">
            <div>
              <p className="text-[10px] font-semibold tracking-[0.2em] uppercase text-zinc-500 mb-0.5">
                The Black Palm
              </p>
              <h1 className="text-base font-bold text-white">Inbox</h1>
            </div>
            {total > 0 && (
              <span className="text-xs text-zinc-500 font-medium bg-zinc-800 px-2 py-0.5 rounded-full">
                {total}
              </span>
            )}
          </div>
          <div className="relative mb-2">
            <svg
              className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-zinc-500 pointer-events-none"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M21 21l-4.35-4.35M17 11A6 6 0 1 1 5 11a6 6 0 0 1 12 0z"
              />
            </svg>
            <input
              type="text"
              placeholder="Search by name or booking ID…"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              className="w-full bg-zinc-800 text-sm text-white placeholder-zinc-500 rounded-lg pl-8 pr-3 py-1.5 outline-none focus:ring-1 focus:ring-blue-600"
            />
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <button
              onClick={() => setUnreadOnly((v) => !v)}
              className={`text-xs font-medium px-3 py-1 rounded-full transition-colors ${
                unreadOnly
                  ? "bg-blue-600 text-white"
                  : "bg-zinc-800 text-zinc-400 hover:text-zinc-200"
              }`}
            >
              Unread only
            </button>

            <FilterDropdown
              label="Platform"
              items={PLATFORM_ITEMS}
              selected={selectedPlatforms}
              onToggle={togglePlatform}
              onClear={clearPlatforms}
            />

            {propertyItems.length > 0 && (
              <FilterDropdown
                label="Property"
                items={propertyItems}
                selected={selectedPropertyIds}
                onToggle={toggleProperty}
                onClear={clearProperties}
              />
            )}
          </div>
        </div>

        {loadingList ? (
          <div className="flex items-center justify-center flex-1 gap-2 text-sm text-zinc-500">
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
            Loading…
          </div>
        ) : (
          <ConversationList
            conversations={conversations}
            selectedId={conversationId ?? null}
            hasMore={hasMore}
            loadingMore={loadingMore}
            onLoadMore={handleLoadMore}
          />
        )}
      </div>

      {/* Right pane */}
      <div className="flex-1 flex flex-col min-w-0">
        {loadingDetail ? (
          <div className="flex items-center justify-center h-full gap-2 text-sm text-zinc-500">
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
            Loading…
          </div>
        ) : detail ? (
          <MessageThread conversation={detail} />
        ) : (
          <div className="flex flex-col items-center justify-center h-full gap-3 text-zinc-600">
            <svg
              className="w-12 h-12 opacity-20"
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
            <p className="text-sm font-medium">Select a conversation</p>
          </div>
        )}
      </div>
    </div>
  );
}
