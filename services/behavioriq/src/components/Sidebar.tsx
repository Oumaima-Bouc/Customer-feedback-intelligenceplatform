'use client';

import React from 'react';
import Image from 'next/image';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { BarChart3, LayoutDashboard, MessageSquare, Settings, X } from 'lucide-react';

interface NavItem {
  id: string;
  label: string;
  description: string;
  href: string;
  icon: React.ElementType;
  badge?: number;
}

interface SidebarProps {
  open?: boolean;
  onClose?: () => void;
}

const navItems: NavItem[] = [
  {
    id: 'nav-dashboard',
    label: 'Dashboard',
    description: 'Executive overview',
    href: '/',
    icon: LayoutDashboard,
  },
  {
    id: 'nav-topics',
    label: 'Mentions',
    description: 'Comments and statistics',
    href: '/topic-intelligence',
    icon: BarChart3,
  },
  {
    id: 'nav-comments',
    label: 'Topics',
    description: 'Sentiment by topic',
    href: '/topic-comments',
    icon: MessageSquare,
  },
];

const bottomNavItems: NavItem[] = [
  {
    id: 'nav-settings',
    label: 'Settings',
    description: 'System controls',
    href: '/system-settings',
    icon: Settings,
  },
];

export default function Sidebar({ open = false, onClose }: SidebarProps) {
  const pathname = usePathname();
  const isActive = (href: string) => (href === '/' ? pathname === '/' : pathname.startsWith(href));

  const renderItems = (items: NavItem[]) =>
    items.map((item) => {
      const NavIcon = item.icon;
      const active = isActive(item.href);
      return (
        <Link
          key={item.id}
          href={item.href}
          onClick={onClose}
          className={`${active ? 'nav-item-active' : 'nav-item'} group min-h-[52px]`}
          aria-current={active ? 'page' : undefined}
        >
          <span
            className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg transition-colors ${
              active
                ? 'bg-primary text-primary-foreground shadow-sm'
                : 'bg-muted text-muted-foreground group-hover:bg-card group-hover:text-foreground'
            }`}
          >
            <NavIcon size={18} />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm leading-5">{item.label}</span>
            <span className="block truncate text-2xs font-medium leading-4 opacity-70">
              {item.description}
            </span>
          </span>
          {item.badge !== undefined && (
            <span className={active ? 'badge-info' : 'badge-negative'}>{item.badge}</span>
          )}
        </Link>
      );
    });

  return (
    <>
      <div
        className={`fixed inset-0 z-40 bg-slate-950/40 backdrop-blur-sm transition-opacity lg:hidden ${
          open ? 'opacity-100' : 'pointer-events-none opacity-0'
        }`}
        onClick={onClose}
      />

      <aside
        className={`fixed left-0 top-0 z-50 flex h-screen w-[var(--sidebar-width)] flex-col overflow-hidden border-r border-border bg-card/95 shadow-2xl shadow-slate-950/10 backdrop-blur-xl transition-transform duration-300 lg:translate-x-0 lg:shadow-none ${
          open ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="flex min-h-[var(--topbar-height)] items-center justify-between border-b border-border px-3">
          <Link href="/" onClick={onClose} className="flex flex-1 items-center">
            <div className="relative h-14 w-full">
              <Image
                src="/assets/images/algerie-telecom-logo.svg"
                alt="Algérie Télécom"
                fill
                priority
                sizes="220px"
                className="object-contain object-left"
                unoptimized
              />
            </div>
          </Link>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground lg:hidden"
            aria-label="Close navigation"
          >
            <X size={18} />
          </button>
        </div>

        <nav className="flex-1 overflow-y-auto px-3 py-5 scrollbar-thin">
          <p className="mb-2 px-3 text-2xs font-bold uppercase tracking-widest text-muted-foreground">
            Intelligence
          </p>
          <div className="space-y-1">{renderItems(navItems)}</div>

          <div className="mt-7">
            <p className="mb-2 px-3 text-2xs font-bold uppercase tracking-widest text-muted-foreground">
              Administration
            </p>
            <div className="space-y-1">{renderItems(bottomNavItems)}</div>
          </div>
        </nav>

        <div className="border-t border-border p-4">
          <div className="rounded-xl border border-border bg-muted/40 p-3">
            <div className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-positive shadow-[0_0_0_4px_var(--positive-bg)]" />
              <span className="text-xs font-bold text-foreground">Data pipeline healthy</span>
            </div>
            <p className="mt-1 text-2xs leading-4 text-muted-foreground">
              Sources are syncing and ready for analysis.
            </p>
          </div>
        </div>
      </aside>
    </>
  );
}
