'use client';

import React, { useState } from 'react';
import { AlertCircle, Loader2, Lock, ShieldCheck, User } from 'lucide-react';
import { useAuth } from '@/lib/auth-context';
import { changePassword as apiChangePassword } from '@/lib/api';

/**
 * Auth gate: renders the login screen when signed out, a forced password-change
 * screen when the account still uses the default password, and the application
 * otherwise. Replaces the previous hardcoded auto-login.
 */
export default function AuthGate({ children }: { children: React.ReactNode }) {
  const { user, loading, mustChangePassword } = useAuth();

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <Loader2 className="animate-spin text-primary" size={28} />
      </div>
    );
  }

  if (!user) return <LoginScreen />;
  if (mustChangePassword) return <ForcePasswordChangeScreen />;
  return <>{children}</>;
}

function AuthShell({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-md">
        <div className="mb-6 flex flex-col items-center text-center">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/assets/images/algerie-telecom-logo.svg"
            alt="Algérie Télécom"
            className="mb-5 h-12 w-auto"
          />
          <h1 className="text-2xl font-extrabold tracking-tight text-foreground">{title}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>
        </div>
        <div className="rounded-2xl border border-border bg-card p-6 shadow-sm">{children}</div>
      </div>
    </div>
  );
}

function FormError({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div className="flex items-start gap-2 rounded-lg border border-negative/20 bg-negative-bg px-3 py-2 text-xs font-semibold text-negative">
      <AlertCircle size={14} className="mt-0.5 shrink-0" />
      <span>{message}</span>
    </div>
  );
}

const inputClass =
  'w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none transition-colors focus:border-primary';
const labelClass = 'mb-1 block text-xs font-bold text-muted-foreground';
const buttonClass =
  'flex w-full items-center justify-center gap-2 rounded-lg gradient-indigo px-4 py-2.5 text-sm font-bold text-white shadow-sm transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60';

function LoginScreen() {
  const { login } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(username.trim(), password);
      // On success the provider re-renders the gate with the authenticated user.
    } catch (err: any) {
      setError(err?.message || 'Sign in failed. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthShell title="Sign in to Algérie Télécom" subtitle="Enter your credentials to continue">
      <form onSubmit={onSubmit} className="space-y-4">
        <FormError message={error} />
        <div>
          <label className={labelClass} htmlFor="username">Username</label>
          <div className="relative">
            <User size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <input
              id="username"
              className={`${inputClass} pl-9`}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              required
              autoFocus
            />
          </div>
        </div>
        <div>
          <label className={labelClass} htmlFor="password">Password</label>
          <div className="relative">
            <Lock size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <input
              id="password"
              type="password"
              className={`${inputClass} pl-9`}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </div>
        </div>
        <button type="submit" className={buttonClass} disabled={submitting || !username || !password}>
          {submitting ? <Loader2 size={16} className="animate-spin" /> : <ShieldCheck size={16} />}
          {submitting ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </AuthShell>
  );
}

function ForcePasswordChangeScreen() {
  const { setMustChangePassword, refreshUser, doLogout } = useAuth();
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (newPassword.length < 8) {
      setError('New password must be at least 8 characters.');
      return;
    }
    if (newPassword !== confirm) {
      setError('New password and confirmation do not match.');
      return;
    }
    if (newPassword === currentPassword) {
      setError('New password must be different from the current password.');
      return;
    }
    setSubmitting(true);
    try {
      await apiChangePassword(currentPassword, newPassword);
      setMustChangePassword(false);
      await refreshUser();
    } catch (err: any) {
      setError(err?.message || 'Could not update password. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthShell
      title="Update your password"
      subtitle="Your account is using a default password. Set a new one to continue."
    >
      <form onSubmit={onSubmit} className="space-y-4">
        <FormError message={error} />
        <div>
          <label className={labelClass} htmlFor="current">Current password</label>
          <input
            id="current"
            type="password"
            className={inputClass}
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
            autoComplete="current-password"
            required
            autoFocus
          />
        </div>
        <div>
          <label className={labelClass} htmlFor="new">New password</label>
          <input
            id="new"
            type="password"
            className={inputClass}
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            autoComplete="new-password"
            required
          />
        </div>
        <div>
          <label className={labelClass} htmlFor="confirm">Confirm new password</label>
          <input
            id="confirm"
            type="password"
            className={inputClass}
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            autoComplete="new-password"
            required
          />
        </div>
        <button type="submit" className={buttonClass} disabled={submitting}>
          {submitting ? <Loader2 size={16} className="animate-spin" /> : <ShieldCheck size={16} />}
          {submitting ? 'Updating…' : 'Update password'}
        </button>
        <button
          type="button"
          onClick={doLogout}
          className="w-full rounded-lg px-4 py-2 text-xs font-bold text-muted-foreground transition-colors hover:text-foreground"
        >
          Sign out
        </button>
      </form>
    </AuthShell>
  );
}
