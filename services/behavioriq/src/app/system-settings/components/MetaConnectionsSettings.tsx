'use client';

import React, { useEffect, useState } from 'react';
import {
  AlertCircle,
  CheckCircle2,
  PauseCircle,
  PlayCircle,
  Plus,
  RadioTower,
  RefreshCw,
  Save,
  Settings2,
  Trash2,
  X,
} from 'lucide-react';
import {
  createSource,
  deleteSource,
  getScraperSettings,
  getSources,
  refreshSource,
  updateScraperSettings,
  updateSource,
} from '@/lib/api';
import {
  getErrorMessage,
  inputClassName,
  PrimaryButton,
  SecondaryButton,
  SettingsAlert,
  SettingsCard,
  SettingsField,
  SettingsPageHeader,
} from './settings-ui';

const FacebookIcon = ({ size = 18 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
    <path d="M13.5 22v-8h2.7l.4-3.1h-3.1V8.9c0-.9.3-1.5 1.6-1.5h1.7V4.6c-.3 0-1.3-.1-2.5-.1-2.5 0-4.2 1.5-4.2 4.3v2.4H7.3V14h2.8v8h3.4z" />
  </svg>
);

const InstagramIcon = ({ size = 18 }: { size?: number }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    aria-hidden="true"
  >
    <rect x="2" y="2" width="20" height="20" rx="5" />
    <path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z" />
    <path d="M17.5 6.5h.01" />
  </svg>
);

function StatusBadge({ connection }: { connection: any }) {
  const base = 'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-bold';
  if (!connection.is_active) {
    return (
      <span className={`${base} bg-muted text-muted-foreground`}>
        <PauseCircle size={14} />
        Paused
      </span>
    );
  }
  if (connection.health_status === 'healthy') {
    return (
      <span className={`${base} bg-positive-bg text-positive`}>
        <CheckCircle2 size={14} />
        Healthy
      </span>
    );
  }
  if (connection.health_status === 'error') {
    return (
      <span className={`${base} bg-negative-bg text-negative`} title={connection.last_error || 'Connection error'}>
        <AlertCircle size={14} />
        Error
      </span>
    );
  }
  return (
    <span className={`${base} bg-muted text-muted-foreground`}>
      <PlayCircle size={14} />
      Checking…
    </span>
  );
}

function PlatformTable({
  title,
  platform,
  countLabel,
  connections,
  icon,
  onAdd,
  onToggle,
  onRefresh,
  onRemove,
}: {
  title: string;
  platform: string;
  countLabel: string;
  connections: any[];
  icon: React.ReactNode;
  onAdd: (platform: string) => void;
  onToggle: (id: number, active: boolean) => void;
  onRefresh: (id: number) => void;
  onRemove: (id: number, name: string) => void;
}) {
  return (
    <SettingsCard
      title={title}
      description={countLabel}
      icon={icon}
      footer={
        <div className="flex justify-end">
          <SecondaryButton onClick={() => onAdd(platform)} className="text-primary">
            <Plus size={16} />
            Add New
          </SecondaryButton>
        </div>
      }
    >
      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] text-left text-sm">
          <thead className="border-b border-border bg-muted/40 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {connections.length === 0 && (
              <tr>
                <td colSpan={3} className="px-4 py-8 text-center text-sm text-muted-foreground">
                  No {title.toLowerCase()} connected
                </td>
              </tr>
            )}
            {connections.map((connection) => (
              <tr key={connection.id} className="hover:bg-muted/30">
                <td className="px-4 py-4">
                  <span className="flex items-center gap-2">
                    <span
                      className={`h-2 w-2 shrink-0 rounded-full ${
                        connection.is_active ? 'bg-positive' : 'bg-muted-foreground'
                      }`}
                    />
                    <span className="flex flex-col gap-0.5">
                      <span className="flex items-center gap-2">
                        <span className="font-semibold text-foreground">
                          {connection.name || connection.external_id}
                        </span>
                        {connection.can_reply === false && (
                          <span className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-2xs font-bold text-muted-foreground" title="Send-replies permission not granted — comments are read-only">
                            Replies off
                          </span>
                        )}
                      </span>
                      <span className="text-xs text-muted-foreground">ID: {connection.external_id}</span>
                      {connection.health_status === 'error' && (
                        <span className="text-xs font-semibold text-negative">
                          {connection.last_error || 'Permission missing'}
                        </span>
                      )}
                    </span>
                  </span>
                </td>
                <td className="px-4 py-4">
                  <StatusBadge connection={connection} />
                </td>
                <td className="px-4 py-4 text-right">
                  <div className="flex items-center justify-end gap-3">
                    <button
                      type="button"
                      onClick={() => onRefresh(connection.id)}
                      className="inline-flex items-center gap-1 text-sm font-semibold text-muted-foreground hover:text-foreground"
                      title="Re-test this connection and refresh its name"
                    >
                      <RefreshCw size={14} />
                      Refresh
                    </button>
                    <button
                      type="button"
                      onClick={() => onToggle(connection.id, connection.is_active)}
                      className="text-sm font-semibold text-primary hover:underline"
                    >
                      {connection.is_active ? 'Pause' : 'Resume'}
                    </button>
                    <button
                      type="button"
                      onClick={() => onRemove(connection.id, connection.name || connection.external_id)}
                      className="inline-flex items-center gap-1 text-sm font-semibold text-negative hover:underline"
                      title="Remove this connection"
                    >
                      <Trash2 size={14} />
                      Remove
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </SettingsCard>
  );
}

export default function MetaConnectionsSettings() {
  const [showAddModal, setShowAddModal] = useState(false);
  const [newScraperPlatform, setNewScraperPlatform] = useState('facebook');
  const [newPageId, setNewPageId] = useState('');
  const [newAccessToken, setNewAccessToken] = useState('');
  const [sources, setSources] = useState<any>({
    facebook: { total: 0, max_allowed: 70, connections: [] },
    instagram: { total: 0, max_allowed: 25, connections: [] },
  });
  const [scraperSettings, setScraperSettings] = useState<any>(null);
  const [intervalHours, setIntervalHours] = useState('4');
  // Single in-section message channel (no floating toasts).
  const [message, setMessage] = useState<{ tone: 'default' | 'danger' | 'success'; text: string } | null>(null);
  const [saving, setSaving] = useState(false);

  const loadSources = () =>
    getSources()
      .then(setSources)
      .catch((error) =>
        setMessage({ tone: 'danger', text: getErrorMessage(error, 'Unable to load scraper sources.') })
      );

  useEffect(() => {
    loadSources();
    getScraperSettings()
      .then((data) => {
        setScraperSettings(data);
        setIntervalHours(String(data.interval_hours || 4));
      })
      .catch((error) =>
        setMessage({ tone: 'danger', text: getErrorMessage(error, 'Unable to load scraper settings.') })
      );
  }, []);

  // Periodically re-pull sources so public-name / health changes (refreshed by
  // the scraper on each run) surface in the UI without a manual reload.
  useEffect(() => {
    const interval = setInterval(() => {
      getSources()
        .then(setSources)
        .catch(() => {
          /* transient errors are ignored on background refresh */
        });
    }, 30000);
    return () => clearInterval(interval);
  }, []);

  const handleCreateSource = async () => {
    // Close the form as soon as Connect is clicked; the outcome is shown in the
    // connections section below (not as a floating toast).
    setShowAddModal(false);

    const platform = newScraperPlatform;
    const pageId = newPageId.trim();
    const token = newAccessToken.trim();
    if (!platform || !pageId || !token) {
      setMessage({ tone: 'danger', text: 'Platform, Page/Profile ID, and Access Token are all required.' });
      return;
    }
    if (token.length < 12) {
      setMessage({ tone: 'danger', text: 'That access token looks too short — paste the full token.' });
      return;
    }

    setSaving(true);
    setMessage({ tone: 'default', text: 'Connecting…' });
    try {
      const result = await createSource({ platform, external_id: pageId, access_token: token });
      setNewPageId('');
      setNewAccessToken('');
      await loadSources();
      const name = result?.name || 'Source';
      if (result?.health_status === 'error' || result?.can_scrape === false) {
        setMessage({
          tone: 'danger',
          text: `Connected ${name}, but comment-read permission is missing. ${
            result?.scrape_reason || 'Grant pages_read_engagement, then Refresh.'
          }`,
        });
      } else if (result?.can_reply === false) {
        setMessage({
          tone: 'default',
          text: `Connected ${name}. Read-only — replies disabled. ${
            result?.reply_reason || 'Grant pages_manage_engagement to enable replies.'
          }`,
        });
      } else {
        setMessage({ tone: 'success', text: `Connected ${name}. Scraping + replies enabled.` });
      }
    } catch (error) {
      setMessage({ tone: 'danger', text: getErrorMessage(error, 'Unable to connect this scraper.') });
    } finally {
      setSaving(false);
    }
  };

  const toggleSource = async (id: number, current: boolean) => {
    try {
      await updateSource(id, { is_active: !current });
      await loadSources();
      setMessage({ tone: 'success', text: current ? 'Source paused.' : 'Source resumed.' });
    } catch (error) {
      setMessage({ tone: 'danger', text: getErrorMessage(error, 'Unable to update this source.') });
    }
  };

  const refreshConnection = async (id: number) => {
    try {
      const result = await refreshSource(id);
      await loadSources();
      if (!result?.ok) {
        setMessage({ tone: 'danger', text: result?.error || 'Connection check failed.' });
        return;
      }
      const name = result?.name || 'Source';
      if (result?.can_scrape === false) {
        setMessage({ tone: 'danger', text: `${name}: comment-read permission missing. ${result?.scrape_reason || ''}`.trim() });
      } else if (result?.can_reply === false) {
        setMessage({ tone: 'default', text: `${name}: scraping OK, replies disabled. ${result?.reply_reason || ''}`.trim() });
      } else {
        setMessage({ tone: 'success', text: `Updated: ${name} — scraping + replies enabled.` });
      }
    } catch (error) {
      setMessage({ tone: 'danger', text: getErrorMessage(error, 'Unable to refresh this source.') });
    }
  };

  const openAddModal = (platform: string) => {
    setNewScraperPlatform(platform);
    setNewPageId('');
    setNewAccessToken('');
    setMessage(null);
    setShowAddModal(true);
  };

  const removeConnection = async (id: number, name: string) => {
    if (!window.confirm(`Remove "${name}"? This stops scraping it and deletes the connection.`)) return;
    try {
      await deleteSource(id);
      await loadSources();
      const next = await getScraperSettings();
      setScraperSettings(next);
      setMessage({ tone: 'success', text: `Removed ${name}.` });
    } catch (error) {
      setMessage({ tone: 'danger', text: getErrorMessage(error, 'Unable to remove this connection.') });
    }
  };

  const activeSources = scraperSettings?.active_sources || 0;
  // Each source needs ~15 min to scrape + let replies dispatch; the interval must fit
  // them all in one cycle. Surfacing this keeps the cadence aligned with the sources.
  const recommendedInterval = Math.max(1, Math.ceil((activeSources * 15) / 60));

  const handleSaveGlobal = async () => {
    const interval = Number(intervalHours);
    if (!Number.isInteger(interval) || interval < 1 || interval > 24) {
      setMessage({ tone: 'danger', text: 'Scraping interval must be a whole number between 1 and 24 hours.' });
      return;
    }
    if (interval < recommendedInterval) {
      setMessage({
        tone: 'danger',
        text: `Interval too short for ${activeSources} active source${activeSources === 1 ? '' : 's'} — use at least ${recommendedInterval}h so every source can scrape and reply each cycle.`,
      });
      return;
    }

    setSaving(true);
    setMessage(null);
    try {
      // Stagger is derived automatically so sources don't all fire at once; it is no
      // longer a user-facing knob.
      const stagger = Math.min(600, Math.max(15, activeSources * 15));
      const result = await updateScraperSettings({
        interval_hours: interval,
        stagger_seconds: stagger,
      });
      const next = await getScraperSettings();
      setScraperSettings(next);
      setMessage({
        tone: 'success',
        text: result?.restart_required_keys?.length
          ? 'Scraper settings saved; restart requested.'
          : 'Scraper settings saved.',
      });
    } catch (error) {
      setMessage({ tone: 'danger', text: getErrorMessage(error, 'Unable to save scraper settings.') });
    } finally {
      setSaving(false);
    }
  };

  const fb = sources?.facebook || { total: 0, max_allowed: 70, connections: [] };
  const ig = sources?.instagram || { total: 0, max_allowed: 25, connections: [] };

  return (
    <div className="space-y-6">
      <SettingsPageHeader
        title="Scraper Settings"
        description="Connect, pause, and monitor Facebook and Instagram harvesting sources."
        action={
          <PrimaryButton onClick={handleSaveGlobal} loading={saving}>
            <Save size={16} />
            Save Changes
          </PrimaryButton>
        }
      />

      {message && <SettingsAlert tone={message.tone}>{message.text}</SettingsAlert>}

      {showAddModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 fade-in">
          <div className="w-full max-w-lg overflow-hidden rounded-xl border border-border bg-card shadow-xl slide-up">
            <div className="flex items-center justify-between border-b border-border px-5 py-4">
              <div>
                <h3 className="text-lg font-bold text-foreground">Add New Scraper</h3>
                <p className="text-sm text-muted-foreground">Connect a managed social source.</p>
              </div>
              <button
                type="button"
                onClick={() => setShowAddModal(false)}
                className="rounded-lg p-2 text-muted-foreground hover:bg-muted hover:text-foreground"
                aria-label="Close add scraper modal"
              >
                <X size={18} />
              </button>
            </div>

            <div className="space-y-5 p-6">
              <SettingsField label="Platform">
                <select
                  className={inputClassName}
                  value={newScraperPlatform}
                  onChange={(event) => setNewScraperPlatform(event.target.value)}
                >
                  <option value="facebook">Facebook</option>
                  <option value="instagram">Instagram</option>
                </select>
              </SettingsField>
              <SettingsField
                label={newScraperPlatform === 'facebook' ? 'Page ID' : 'Profile ID'}
                description="We test the connection live and detect the public name automatically."
              >
                <input
                  type="text"
                  value={newPageId}
                  onChange={(event) => setNewPageId(event.target.value)}
                  placeholder="e.g. 10293847565"
                  className={inputClassName}
                />
              </SettingsField>
              <SettingsField
                label="Access Token"
                description="Use a long-lived token with the required read permissions."
              >
                <input
                  type="password"
                  value={newAccessToken}
                  onChange={(event) => setNewAccessToken(event.target.value)}
                  placeholder="Enter access token"
                  className={inputClassName}
                  autoComplete="off"
                />
              </SettingsField>
            </div>

            <div className="flex flex-col gap-3 border-t border-border bg-muted/20 px-5 py-4 sm:flex-row sm:justify-end">
              <SecondaryButton onClick={() => setShowAddModal(false)}>Cancel</SecondaryButton>
              <PrimaryButton onClick={handleCreateSource} loading={saving}>
                Connect Scraper
              </PrimaryButton>
            </div>
          </div>
        </div>
      )}

      <PlatformTable
        title="Facebook Pages"
        platform="facebook"
        countLabel={`${fb.total}/${fb.max_allowed || 70} pages used`}
        connections={fb.connections || []}
        icon={<FacebookIcon />}
        onAdd={openAddModal}
        onToggle={toggleSource}
        onRefresh={refreshConnection}
        onRemove={removeConnection}
      />

      <PlatformTable
        title="Instagram Profiles"
        platform="instagram"
        countLabel={`${ig.total}/${ig.max_allowed || 25} profiles used`}
        connections={ig.connections || []}
        icon={<InstagramIcon />}
        onAdd={openAddModal}
        onToggle={toggleSource}
        onRefresh={refreshConnection}
        onRemove={removeConnection}
      />

      <SettingsCard
        title="Global Scraper Configuration"
        description="How often every active source is scraped. The cadence is aligned to the number of active sources so each one has time to scrape and reply per cycle."
        icon={<Settings2 size={18} />}
      >
        <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
          <SettingsField
            label="Scraping Interval (hours)"
            description={`Recommended at least ${recommendedInterval}h for ${activeSources} active source${activeSources === 1 ? '' : 's'}.`}
          >
            <input
              type="number"
              min={1}
              max={24}
              value={intervalHours}
              onChange={(event) => setIntervalHours(event.target.value)}
              className={inputClassName}
            />
          </SettingsField>
          <div className="rounded-lg border border-border bg-muted/30 p-4">
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold text-foreground">Active Sources</span>
              <span className="inline-flex items-center gap-2 rounded-full bg-primary/10 px-3 py-1 text-sm font-bold text-primary">
                <RadioTower size={15} />
                {activeSources}
              </span>
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              Sources are staggered automatically across each cycle.
            </p>
          </div>
        </div>
      </SettingsCard>
    </div>
  );
}
