'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { usePathname } from 'next/navigation';
import {
  Briefcase,
  Calendar,
  ChevronDown,
  Clock,
  Loader2,
  LogOut,
  Mail,
  Menu,
  Play,
} from 'lucide-react';
import { toast } from 'sonner';
import { useAuth } from '@/lib/auth-context';
import { getSystemRunStatus, triggerSystemRun, SystemRunStatus } from '@/lib/api';

interface TopbarProps {
  onMenuClick?: () => void;
}

const PAGE_TITLES: { match: (pathname: string) => boolean; title: string; subtitle: string }[] = [
  {
    match: (pathname) => pathname === '/',
    title: 'Dashboard',
    subtitle: 'Customer behavior intelligence overview',
  },
  {
    match: (pathname) => pathname.startsWith('/topic-intelligence'),
    title: 'Mentions',
    subtitle: 'Comments, filters, and source-level statistics',
  },
  {
    match: (pathname) => pathname.startsWith('/topic-comments'),
    title: 'Topics',
    subtitle: 'Topic sentiment and recent comment evidence',
  },
  {
    match: (pathname) => pathname.startsWith('/system-settings'),
    title: 'System Settings',
    subtitle: 'Account, scraping, pipeline, and visualization controls',
  },
];

export default function Topbar({ onMenuClick }: TopbarProps) {
  const pathname = usePathname();
  const [profileOpen, setProfileOpen] = useState(false);
  const [currentDateTime, setCurrentDateTime] = useState<Date | null>(null);
  const profileRef = useRef<HTMLDivElement>(null);
  const { user, doLogout } = useAuth();

  /* ── Manual full-system run (scrape → pipeline → reload) ── */
  const [run, setRun] = useState<SystemRunStatus | null>(null);
  const [starting, setStarting] = useState(false);
  const wasRunning = useRef(false);
  const canRun = ['admin', 'editor'].includes((user?.role || '').toLowerCase());

  useEffect(() => {
    getSystemRunStatus()
      .then((s) => {
        setRun(s);
        wasRunning.current = s.running;
      })
      .catch(() => {});
  }, []);

  // Poll while a run is active.
  useEffect(() => {
    if (!run?.running) return;
    const id = setInterval(() => {
      getSystemRunStatus().then(setRun).catch(() => {});
    }, 4000);
    return () => clearInterval(id);
  }, [run?.running]);

  // On running → finished transition, reload the data (success) or surface the error.
  useEffect(() => {
    if (!run) return;
    const finishedNow = wasRunning.current && !run.running;
    wasRunning.current = run.running;
    if (!finishedNow) return;
    if (run.phase === 'done') {
      toast.success('Run complete — refreshing data…');
      setTimeout(() => window.location.reload(), 900);
    } else if (run.phase === 'failed') {
      toast.error(`Run failed: ${run.error || 'unknown error'}`);
    }
  }, [run]);

  const handleRun = useCallback(async () => {
    setStarting(true);
    try {
      await triggerSystemRun();
      toast.success('Run started — scraping, then analyzing…');
      const s = await getSystemRunStatus();
      setRun(s);
      wasRunning.current = s.running;
    } catch (e: any) {
      const msg = e?.message || '';
      if (msg.includes('409') || /in progress/i.test(msg)) {
        toast.error('A run is already in progress.');
        getSystemRunStatus().then(setRun).catch(() => {});
      } else {
        toast.error('Could not start the run.');
      }
    } finally {
      setStarting(false);
    }
  }, []);

  const isRunning = !!run?.running;
  const runLabel =
    run?.phase === 'scraping'
      ? 'Scraping…'
      : run?.phase === 'analyzing'
        ? 'Analyzing…'
        : starting
          ? 'Starting…'
          : 'Run now';

  useEffect(() => {
    setCurrentDateTime(new Date());
    const interval = setInterval(() => setCurrentDateTime(new Date()), 1000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const handler = (event: MouseEvent) => {
      if (profileRef.current && !profileRef.current.contains(event.target as Node)) {
        setProfileOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const page = PAGE_TITLES.find((item) => item.match(pathname)) || {
    title: '',
    subtitle: '',
  };

  return (
    <header className="fixed right-0 top-0 z-30 flex h-[var(--topbar-height)] items-center gap-3 border-b border-border bg-card/85 px-4 shadow-sm shadow-slate-950/[0.03] backdrop-blur-xl transition-all duration-300 lg:left-[var(--sidebar-width)] sm:px-6">
      <button
        type="button"
        onClick={onMenuClick}
        className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-border bg-card text-muted-foreground hover:bg-muted hover:text-foreground lg:hidden"
        aria-label="Open navigation"
      >
        <Menu size={20} />
      </button>

      <div className="min-w-0 flex-1">
        <h1 className="truncate text-lg font-extrabold tracking-tight text-foreground sm:text-xl">
          {page.title}
        </h1>
        <p className="hidden truncate text-xs font-medium text-muted-foreground sm:block">
          {page.subtitle}
        </p>
      </div>

      {currentDateTime && (
        <div className="hidden items-center gap-2 rounded-lg border border-border bg-muted/40 px-3 py-2 text-xs font-semibold text-muted-foreground xl:flex">
          <Calendar size={14} className="opacity-70" />
          <span>
            {currentDateTime.toLocaleDateString(undefined, {
              weekday: 'short',
              month: 'short',
              day: 'numeric',
            })}
          </span>
          <span className="h-4 w-px bg-border" />
          <Clock size={14} className="opacity-70" />
          <span>
            {currentDateTime.toLocaleTimeString(undefined, {
              hour: '2-digit',
              minute: '2-digit',
            })}
          </span>
        </div>
      )}

      {canRun ? (
        <button
          type="button"
          onClick={handleRun}
          disabled={isRunning || starting}
          title={
            isRunning
              ? 'A full run is in progress'
              : 'Run the full pipeline now: scrape every source, analyze, then refresh'
          }
          className="inline-flex items-center gap-2 rounded-full px-3.5 py-1.5 text-xs font-bold text-white transition-all duration-150 active:scale-[0.98] disabled:cursor-not-allowed"
          style={{
            backgroundColor: isRunning ? 'var(--warning)' : 'var(--primary)',
            opacity: isRunning || starting ? 0.85 : 1,
            boxShadow: '0 8px 20px -14px rgba(14,95,168,0.7)',
          }}
        >
          {isRunning || starting ? (
            <Loader2 size={13} className="animate-spin" />
          ) : (
            <Play size={13} className="fill-current" />
          )}
          {runLabel}
        </button>
      ) : (
        <div className="hidden items-center gap-2 rounded-full border border-positive/20 bg-positive-bg px-3 py-1.5 text-xs font-bold text-positive md:flex">
          <span
            className={`h-1.5 w-1.5 rounded-full ${isRunning ? 'bg-warning animate-pulse' : 'bg-positive'}`}
          />
          {isRunning ? 'Syncing…' : 'Synced'}
        </div>
      )}

      <div ref={profileRef} className="relative">
        <button
          type="button"
          className="flex h-10 items-center gap-2 rounded-lg border border-transparent bg-transparent pl-1 pr-2 transition-all duration-150 hover:border-border hover:bg-muted"
          onClick={() => setProfileOpen((open) => !open)}
          aria-expanded={profileOpen}
          aria-haspopup="menu"
        >
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg gradient-indigo text-xs font-black text-white shadow-sm">
            {(user?.username || 'A').charAt(0).toUpperCase()}
          </div>
          <span className="hidden max-w-[120px] truncate text-sm font-bold text-foreground lg:block">
            {user?.username || 'Admin'}
          </span>
          <ChevronDown
            size={14}
            className={`hidden text-muted-foreground transition-transform duration-200 lg:block ${
              profileOpen ? 'rotate-180' : ''
            }`}
          />
        </button>

        {profileOpen && (
          <div
            role="menu"
            className="absolute right-0 mt-2 w-72 overflow-hidden rounded-xl border border-border bg-card shadow-[var(--shadow-popover)] fade-in"
          >
            <div className="border-b border-border bg-muted/35 p-4">
              <div className="flex items-center gap-3">
                <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl gradient-indigo text-lg font-black text-white shadow-sm">
                  {(user?.username || 'A').charAt(0).toUpperCase()}
                </div>
                <div className="min-w-0">
                  <h3 className="truncate text-sm font-extrabold capitalize text-foreground">
                    {user?.username || 'Admin'}
                  </h3>
                  <p className="truncate text-xs font-bold capitalize text-primary">
                    {user?.role || 'Administrator'}
                  </p>
                </div>
              </div>
            </div>
            <div className="p-2">
              <div className="flex items-center gap-3 rounded-lg px-3 py-2 text-xs text-muted-foreground">
                <Mail size={14} className="shrink-0 opacity-70" />
                <span className="truncate">{user?.email || 'admin@example.com'}</span>
              </div>
              <div className="flex items-center gap-3 rounded-lg px-3 py-2 text-xs text-muted-foreground">
                <Briefcase size={14} className="shrink-0 opacity-70" />
                <span className="truncate">System Administrator</span>
              </div>
            </div>
            <div className="border-t border-border p-2">
              <button
                type="button"
                onClick={doLogout}
                className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs font-bold text-negative transition-colors hover:bg-negative-bg"
              >
                <LogOut size={14} />
                Sign Out
              </button>
            </div>
          </div>
        )}
      </div>
    </header>
  );
}
