// All dashboard state and API calls in one hook, so components stay presentational.
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { mergeEvents } from "./present";
import type { ApprovalsResponse, AuditEvent, CashResponse, HealthResponse, Ticket, TicketRunResponse } from "./types";

export interface Loadable<T> { data: T | null; loading: boolean; error: string | null }
const initial = <T,>(): Loadable<T> => ({ data: null, loading: true, error: null });

export type RunPhase = "running" | "completed" | "limit_reached" | "error";
export interface RunView {
  phase: RunPhase;
  result: TicketRunResponse | null;
  error: string | null;
  startedAt: string;
}

const msg = (e: unknown) => (e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e));

export function useDesk({ pollMs = 1500 }: { pollMs?: number } = {}) {
  const [tickets, setTickets] = useState<Loadable<Ticket[]>>(initial);
  const [cash, setCash] = useState<Loadable<CashResponse>>(initial);
  const [approvals, setApprovals] = useState<Loadable<ApprovalsResponse>>(initial);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [feeds, setFeeds] = useState<Record<number, AuditEvent[]>>({});
  const [feedErrors, setFeedErrors] = useState<Record<number, string | null>>({});
  const [runs, setRuns] = useState<Record<number, RunView>>({});
  const activeRuns = useRef(new Set<number>());

  const load = useCallback(async <T,>(fn: () => Promise<T>, set: (u: (p: Loadable<T>) => Loadable<T>) => void) => {
    set((p) => ({ ...p, loading: true }));
    try {
      const data = await fn();
      set(() => ({ data, loading: false, error: null }));
    } catch (e) {
      set((p) => ({ data: p.data, loading: false, error: msg(e) }));
    }
  }, []);

  const refreshTickets = useCallback(() => load(async () => (await api.tickets()).tickets, setTickets), [load]);
  const refreshCash = useCallback(() => load(api.cash, setCash), [load]);
  const refreshApprovals = useCallback(() => load(api.approvals, setApprovals), [load]);
  const refreshHealth = useCallback(async () => {
    try { setHealth(await api.health()); } catch { setHealth(null); }
  }, []);

  const addEvents = useCallback((ticketId: number, events: AuditEvent[]) => {
    setFeeds((f) => {
      const merged = mergeEvents(f[ticketId] ?? [], events);
      return merged === f[ticketId] ? f : { ...f, [ticketId]: merged };
    });
  }, []);

  /** Recent history for one ticket (newest 500 events, oldest first). */
  const loadFeed = useCallback(async (ticketId: number) => {
    try {
      const r = await api.events({ ticket_id: ticketId, limit: 500 });
      addEvents(ticketId, r.events);
      setFeedErrors((f) => ({ ...f, [ticketId]: null }));
    } catch (e) {
      setFeedErrors((f) => ({ ...f, [ticketId]: msg(e) }));
    }
  }, [addEvents]);

  const refreshAll = useCallback(async () => {
    await Promise.all([refreshTickets(), refreshCash(), refreshApprovals(), refreshHealth()]);
  }, [refreshTickets, refreshCash, refreshApprovals, refreshHealth]);

  useEffect(() => { void refreshAll(); }, [refreshAll]);

  /**
   * Start the agent team. The backend's POST only returns when the run ends, so we
   * fire it without awaiting and poll the audit trail (cursor = last event seen)
   * until it settles. Events are merged by event_id, so nothing is shown twice.
   */
  const startRun = useCallback(async (ticketId: number) => {
    if (activeRuns.current.has(ticketId)) return; // no duplicate runs from this tab
    activeRuns.current.add(ticketId);
    setRuns((r) => ({ ...r, [ticketId]: { phase: "running", result: null, error: null, startedAt: new Date().toISOString() } }));

    let cursor: string | undefined;
    try {
      cursor = (await api.events({ limit: 1 })).events.at(-1)?.event_id;
    } catch { /* empty or unreadable trail: poll without a cursor; merge de-duplicates */ }

    let inflight = false;
    const poll = async () => {
      if (inflight) return;
      inflight = true;
      try {
        const r = await api.events({ ticket_id: ticketId, after: cursor, limit: 1000 });
        if (r.events.length) {
          cursor = r.events[r.events.length - 1].event_id;
          addEvents(ticketId, r.events);
        }
      } catch { /* transient; the next tick retries */ } finally {
        inflight = false;
      }
    };
    const timer = setInterval(poll, pollMs);
    const runRequest = api.runTicket(ticketId); // not awaited before polling starts
    void refreshTickets(); // picks up run_in_progress from the backend

    let view: RunView;
    try {
      const result = await runRequest;
      view = { phase: result.state === "running" ? "completed" : result.state, result, error: result.error, startedAt: result.started_at };
    } catch (e) {
      // 502 returns a TicketRunResponse body; 404/409/503 return {detail}
      const body = e instanceof ApiError ? (e.body as Partial<TicketRunResponse> | null) : null;
      const result = body && typeof body === "object" && "state" in body ? (body as TicketRunResponse) : null;
      view = { phase: "error", result, error: msg(e), startedAt: result?.started_at ?? new Date().toISOString() };
    } finally {
      clearInterval(timer);
      activeRuns.current.delete(ticketId);
    }
    await poll();
    setRuns((r) => ({ ...r, [ticketId]: view }));
    await refreshAll();
  }, [addEvents, pollMs, refreshAll, refreshTickets]);

  /** Approve or decline; on any error nothing is assumed to have happened. */
  const decide = useCallback(async (
    action: "approve" | "decline",
    args: { request_id: string; name: string; amount?: number; reason?: string; ticket_id: number | null },
  ) => {
    try {
      const res = action === "approve"
        ? await api.approve({ request_id: args.request_id, approve: true, approved_by: args.name.trim(), approved_amount: args.amount! })
        : await api.decline({ request_id: args.request_id, decline: true, declined_by: args.name.trim(), reason: args.reason?.trim() || null });
      return { ok: true as const, message: res.message, status: res.status };
    } catch (e) {
      return { ok: false as const, message: msg(e), status: e instanceof ApiError ? e.status : 0 };
    } finally {
      await refreshAll();
      if (args.ticket_id !== null) await loadFeed(args.ticket_id);
    }
  }, [loadFeed, refreshAll]);

  const reset = useCallback(async () => {
    try {
      const r = await api.reset();
      setRuns({});
      return { ok: true as const, message: r.message };
    } catch (e) {
      return { ok: false as const, message: msg(e) };
    } finally {
      await refreshAll();
    }
  }, [refreshAll]);

  return {
    tickets, cash, approvals, health, feeds, feedErrors, runs,
    refreshAll, refreshTickets, refreshCash, refreshApprovals, loadFeed, startRun, decide, reset,
  };
}

export type Desk = ReturnType<typeof useDesk>;
