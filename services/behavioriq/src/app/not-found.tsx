'use client';

import React from 'react';
import { ArrowLeft, Home } from 'lucide-react';
import { useRouter } from 'next/navigation';

export default function NotFound() {
  const router = useRouter();

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <div className="panel max-w-lg p-8 text-center">
        <div className="mx-auto mb-6 flex h-20 w-20 items-center justify-center rounded-2xl bg-primary/10 text-4xl font-black text-primary">
          404
        </div>
        <h1 className="text-2xl font-extrabold tracking-tight text-foreground">Page Not Found</h1>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          The page you are looking for does not exist or is no longer available.
        </p>

        <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:justify-center">
          <button type="button" onClick={() => router.back()} className="btn-secondary">
            <ArrowLeft size={16} />
            Go Back
          </button>
          <button type="button" onClick={() => router.push('/')} className="btn-primary">
            <Home size={16} />
            Dashboard
          </button>
        </div>
      </div>
    </div>
  );
}
