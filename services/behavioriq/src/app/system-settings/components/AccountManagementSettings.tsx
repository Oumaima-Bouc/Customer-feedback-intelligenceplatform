'use client';

import React, { useEffect, useState } from 'react';
import { KeyRound, LogOut, Save, ShieldCheck, UserRound } from 'lucide-react';
import { toast } from 'sonner';
import { changePassword, getMe, logout, updateUser } from '@/lib/api';
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

type FieldErrors = Partial<
  Record<'username' | 'email' | 'oldPassword' | 'newPassword' | 'form', string>
>;

export default function AccountManagementSettings() {
  const [user, setUser] = useState<any>(null);
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [errors, setErrors] = useState<FieldErrors>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getMe()
      .then((u) => {
        setUser(u);
        setUsername(u?.username || '');
        setEmail(u?.email || '');
      })
      .catch((error) => {
        setErrors({ form: getErrorMessage(error, 'Unable to load account details.') });
      })
      .finally(() => setLoading(false));
  }, []);

  const validate = () => {
    const nextErrors: FieldErrors = {};

    if (!username.trim()) nextErrors.username = 'Username is required.';
    if (!email.trim()) {
      nextErrors.email = 'Email is required.';
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      nextErrors.email = 'Enter a valid email address.';
    }

    if (oldPassword || newPassword) {
      if (!oldPassword) nextErrors.oldPassword = 'Enter your current password.';
      if (!newPassword) nextErrors.newPassword = 'Enter a new password.';
      if (newPassword && newPassword.length < 8) {
        nextErrors.newPassword = 'Use at least 8 characters.';
      }
      if (oldPassword && newPassword && oldPassword === newPassword) {
        nextErrors.newPassword = 'New password must be different from the current password.';
      }
    }

    setErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  };

  const refreshUser = async () => {
    const nextUser = await getMe();
    setUser(nextUser);
    setUsername(nextUser?.username || '');
    setEmail(nextUser?.email || '');
  };

  const handleSave = async () => {
    if (!user || !validate()) return;

    setSaving(true);
    setErrors({});
    try {
      if (username !== user.username || email !== user.email) {
        await updateUser(user.id || user.sub, { username, email });
      }
      if (oldPassword && newPassword) {
        await changePassword(oldPassword, newPassword);
        setOldPassword('');
        setNewPassword('');
      }
      await refreshUser();
      toast.success('Account settings saved');
    } catch (error) {
      const message = getErrorMessage(error, 'Unable to save account settings.');
      const lower = message.toLowerCase();
      if (
        lower.includes('password') ||
        lower.includes('credential') ||
        lower.includes('incorrect')
      ) {
        setErrors({ oldPassword: message });
      } else if (lower.includes('email')) {
        setErrors({ email: message });
      } else if (lower.includes('username')) {
        setErrors({ username: message });
      } else {
        setErrors({ form: message });
      }
      toast.error('Account settings were not saved');
    } finally {
      setSaving(false);
    }
  };

  const handleLogout = async () => {
    try {
      await logout();
    } catch {
      // Logout should still clear the local session when the server call fails.
    }
    localStorage.removeItem('biq_token');
    window.location.reload();
  };

  const role = user?.role || 'Administrator';
  const isActive = user?.is_active ?? true;

  return (
    <div className="space-y-6">
      <SettingsPageHeader
        title="Account Management"
        description="Manage profile identity, password changes, and the current account session."
        action={
          <PrimaryButton onClick={handleSave} loading={saving || loading}>
            <Save size={16} />
            Save Changes
          </PrimaryButton>
        }
      />

      {errors.form && <SettingsAlert tone="danger">{errors.form}</SettingsAlert>}

      <SettingsCard
        title="Profile"
        description="Keep the account details visible to analysts and administrators up to date."
        icon={<UserRound size={18} />}
      >
        <div className="mb-6 flex flex-col gap-4 rounded-lg border border-border bg-muted/30 p-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-4">
            <div className="flex h-14 w-14 items-center justify-center rounded-lg bg-primary/10 text-xl font-black text-primary">
              {(username || 'A').charAt(0).toUpperCase()}
            </div>
            <div>
              <p className="text-sm font-semibold text-foreground">{role}</p>
              <p className="text-xs text-muted-foreground">Current permission level</p>
            </div>
          </div>
          <span
            className={`inline-flex w-fit items-center gap-1.5 rounded-full px-3 py-1 text-xs font-bold ${
              isActive ? 'bg-positive-bg text-positive' : 'bg-negative-bg text-negative'
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${isActive ? 'bg-positive' : 'bg-negative'}`}
            />
            {isActive ? 'Active' : 'Inactive'}
          </span>
        </div>

        <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
          <SettingsField label="Username" error={errors.username}>
            <input
              type="text"
              value={username}
              disabled={loading}
              onChange={(event) => setUsername(event.target.value)}
              className={inputClassName}
            />
          </SettingsField>
          <SettingsField label="Email Address" error={errors.email}>
            <input
              type="email"
              value={email}
              disabled={loading}
              onChange={(event) => setEmail(event.target.value)}
              className={inputClassName}
            />
          </SettingsField>
        </div>
      </SettingsCard>

      <SettingsCard
        title="Password"
        description="Enter your current password before setting a new one. Incorrect current passwords are shown here."
        icon={<KeyRound size={18} />}
      >
        <div className="grid grid-cols-1 gap-5 md:grid-cols-2 md:items-start">
          <SettingsField
            label="Current Password"
            description="Required when changing your password."
            error={errors.oldPassword}
          >
            <input
              type="password"
              value={oldPassword}
              onChange={(event) => setOldPassword(event.target.value)}
              placeholder="Enter current password"
              className={inputClassName}
              autoComplete="current-password"
            />
          </SettingsField>
          <SettingsField
            label="New Password"
            description="Use at least 8 characters."
            error={errors.newPassword}
          >
            <input
              type="password"
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              placeholder="Leave blank to keep unchanged"
              className={inputClassName}
              autoComplete="new-password"
            />
          </SettingsField>
        </div>
      </SettingsCard>

      <SettingsCard
        title="Account Session"
        description="End the current authenticated session on this browser."
        icon={<ShieldCheck size={18} />}
        tone="danger"
        footer={
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm text-muted-foreground">
              Logging out removes the local access token and reloads the application.
            </p>
            <SecondaryButton
              onClick={handleLogout}
              className="border-negative text-negative hover:bg-negative-bg"
            >
              <LogOut size={16} />
              Log Out
            </SecondaryButton>
          </div>
        }
      >
        <SettingsAlert>
          Use this when you are done working on a shared workstation or need to refresh your
          session.
        </SettingsAlert>
      </SettingsCard>
    </div>
  );
}
