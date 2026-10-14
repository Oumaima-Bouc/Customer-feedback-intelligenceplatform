'use client';

import React from 'react';
import { AlertCircle, CheckCircle2, Loader2 } from 'lucide-react';

type Tone = 'default' | 'danger' | 'success';

export function getErrorMessage(
  error: unknown,
  fallback = 'Something went wrong. Please try again.'
) {
  if (error instanceof Error) {
    const match = error.message.match(/\{[\s\S]*\}$/);
    if (match) {
      try {
        const parsed = JSON.parse(match[0]);
        if (typeof parsed.detail === 'string') return parsed.detail;
        if (Array.isArray(parsed.detail)) {
          return parsed.detail
            .map((item: any) => item?.msg || item?.message)
            .filter(Boolean)
            .join(' ');
        }
      } catch {
        // Fall back to the raw API message when the payload is not JSON.
      }
    }
    return error.message.replace(/^API\s+[^\s]+\s+failed:\s+\d+\s*/i, '') || fallback;
  }
  return fallback;
}

export function SettingsPageHeader({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      <div>
        <h2 className="text-2xl font-bold tracking-tight text-foreground">{title}</h2>
        <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">{description}</p>
      </div>
      {action}
    </div>
  );
}

export function SettingsCard({
  title,
  description,
  icon,
  children,
  footer,
  tone = 'default',
}: {
  title: string;
  description?: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
  tone?: Tone;
}) {
  const border = tone === 'danger' ? 'border-negative/30' : 'border-border';
  return (
    <section className={`overflow-hidden rounded-xl border ${border} bg-card card-shadow`}>
      <div className="flex items-start gap-3 border-b border-border bg-muted/30 px-5 py-4">
        {icon && (
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
            {icon}
          </div>
        )}
        <div>
          <h3 className="text-base font-bold text-foreground">{title}</h3>
          {description && <p className="mt-0.5 text-sm text-muted-foreground">{description}</p>}
        </div>
      </div>
      <div className="p-5 sm:p-6">{children}</div>
      {footer && <div className="border-t border-border bg-muted/20 px-5 py-4">{footer}</div>}
    </section>
  );
}

export function SettingsField({
  label,
  description,
  error,
  children,
}: {
  label: string;
  description?: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="text-sm font-semibold text-foreground">{label}</span>
      {description && (
        <span className="mt-1 block text-xs leading-5 text-muted-foreground">{description}</span>
      )}
      <div className="mt-2">{children}</div>
      {error && (
        <span className="mt-1.5 flex items-center gap-1.5 text-xs font-medium text-negative">
          <AlertCircle size={13} />
          {error}
        </span>
      )}
    </label>
  );
}

export function SettingsAlert({
  tone = 'default',
  children,
}: {
  tone?: 'default' | 'danger' | 'success';
  children: React.ReactNode;
}) {
  const styles = {
    default: 'border-info/25 bg-info-bg text-info',
    danger: 'border-negative/25 bg-negative-bg text-negative',
    success: 'border-positive/25 bg-positive-bg text-positive',
  };
  const Icon = tone === 'success' ? CheckCircle2 : AlertCircle;
  return (
    <div
      className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-sm font-medium ${styles[tone]}`}
    >
      <Icon size={16} className="mt-0.5 shrink-0" />
      <span className="leading-5">{children}</span>
    </div>
  );
}

export function PrimaryButton({
  children,
  loading,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { loading?: boolean }) {
  return (
    <button
      {...props}
      disabled={loading || props.disabled}
      className={`btn-primary disabled:cursor-not-allowed disabled:opacity-60 ${props.className || ''}`}
    >
      {loading && <Loader2 size={15} className="animate-spin" />}
      {children}
    </button>
  );
}

export function SecondaryButton(props: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button {...props} className={`btn-secondary ${props.className || ''}`} />;
}

export const inputClassName =
  'input-base bg-card disabled:cursor-not-allowed disabled:bg-muted/60 disabled:text-muted-foreground';
