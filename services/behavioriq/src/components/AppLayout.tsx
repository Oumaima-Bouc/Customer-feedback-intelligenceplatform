'use client';

import React, { useState } from 'react';
import Sidebar from './Sidebar';
import Topbar from './Topbar';

interface AppLayoutProps {
  children: React.ReactNode;
}

export default function AppLayout({ children }: AppLayoutProps) {
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);

  return (
    <div className="min-h-screen bg-background text-foreground">
      <Sidebar open={mobileSidebarOpen} onClose={() => setMobileSidebarOpen(false)} />
      <Topbar onMenuClick={() => setMobileSidebarOpen(true)} />

      <main className="min-h-screen pt-[var(--topbar-height)] transition-all duration-300 lg:pl-[var(--sidebar-width)]">
        <div className="app-page">{children}</div>
      </main>
    </div>
  );
}
