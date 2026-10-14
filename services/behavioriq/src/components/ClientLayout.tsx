'use client';

import React from 'react';
import { AuthProvider } from '@/lib/auth-context';
import AuthGate from '@/components/AuthGate';

export default function ClientLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <AuthGate>{children}</AuthGate>
    </AuthProvider>
  );
}
