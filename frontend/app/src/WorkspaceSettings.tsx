import { useEffect, useState } from 'react'
import {
  Bell,
  BuildingOffice,
  Check,
  Database,
  Globe,
  Plus,
  ShieldCheck,
  Storefront,
  Trash,
  UsersThree,
  WarningCircle,
  type Icon,
} from '@phosphor-icons/react'
import { Badge, Button, Switch } from '@radix-ui/themes'
import { apiRequest, apiRequestWithHeaders, businessPath, type Business, type Integration } from './api'
import './WorkspaceSettings.css'

type SettingsTab = 'Business profile' | 'Team' | 'Notifications' | 'Data & privacy'

type BusinessSettings = {
  businessName: string
  supportEmail: string
  phone: string
  website: string
  country: string
  currency: string
  timezone: string
  returnPolicy: string
  deliveryPolicy: string
}

type TeamMember = {
  id: string
  name: string
  email: string
  role: 'owner' | 'admin' | 'staff' | 'read_only'
  initials: string
}

type SettingsApi = {
  business: Business & {
    country: string | null
    support_email: string | null
    phone: string | null
    website: string | null
    return_policy: string | null
    delivery_policy: string | null
  }
  notifications: {
    new_conversations: boolean
    approval_requests: boolean
    payment_updates: boolean
    weekly_summary: boolean
  }
  privacy: Record<string, string | number | boolean | null>
}

type MemberApi = { id: string; user_id: string; email?: string | null; display_name?: string | null; role: TeamMember['role'] }
type InvitationApi = { id: string; email: string; role: TeamMember['role']; status: string }

const tabs: { label: SettingsTab; icon: Icon }[] = [
  { label: 'Business profile', icon: BuildingOffice },
  { label: 'Team', icon: UsersThree },
  { label: 'Notifications', icon: Bell },
  { label: 'Data & privacy', icon: ShieldCheck },
]

function toSettings(data: SettingsApi): BusinessSettings {
  return {
    businessName: data.business.name,
    supportEmail: data.business.support_email ?? '',
    phone: data.business.phone ?? '',
    website: data.business.website ?? '',
    country: data.business.country ?? '',
    currency: data.business.currency,
    timezone: data.business.timezone,
    returnPolicy: data.business.return_policy ?? '',
    deliveryPolicy: data.business.delivery_policy ?? '',
  }
}

function roleLabel(role: TeamMember['role']) {
  return role === 'read_only' ? 'Read only' : role[0].toUpperCase() + role.slice(1)
}

function initialsFor(name?: string | null) {
  if (!name?.trim()) return 'WM'
  return name.trim().split(/\s+/).slice(0, 2).map((part) => part[0] ?? '').join('').toUpperCase() || 'WM'
}

export default function WorkspaceSettings({
  businessId,
  business,
  integrations,
  notify,
  onBusinessUpdated,
  openIntegrations,
}: {
  businessId: string
  business: Business
  integrations: Integration[]
  notify: (message: string) => void
  onBusinessUpdated: (business: SettingsApi['business']) => void
  openIntegrations: () => void
}) {
  const [settings, setSettings] = useState<BusinessSettings>({
    businessName: business.name,
    supportEmail: '',
    phone: '',
    website: '',
    country: '',
    currency: business.currency,
    timezone: business.timezone,
    returnPolicy: '',
    deliveryPolicy: '',
  })
  const [activeTab, setActiveTab] = useState<SettingsTab>('Business profile')
  const [saveMessage, setSaveMessage] = useState('')
  const [loadError, setLoadError] = useState('')
  const [etag, setEtag] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [team, setTeam] = useState<TeamMember[]>([])
  const [teamLoading, setTeamLoading] = useState(true)
  const [teamError, setTeamError] = useState('')
  const [privacy, setPrivacy] = useState<SettingsApi['privacy']>({})
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState<'admin' | 'staff' | 'read_only'>('staff')
  const [inviteError, setInviteError] = useState('')
  const [inviting, setInviting] = useState(false)
  const [notificationPreferences, setNotificationPreferences] = useState<SettingsApi['notifications']>({
    new_conversations: true,
    approval_requests: true,
    payment_updates: true,
    weekly_summary: true,
  })
  const canManage = business.role === 'owner' || business.role === 'admin'

  useEffect(() => {
    let active = true
    void Promise.all([
      apiRequestWithHeaders<SettingsApi>(businessPath(businessId, '/settings')).then(({ data, headers }) => {
        if (!active) return
        const responseEtag = headers.get('ETag')
        if (!responseEtag) throw new Error('The settings response is missing its version. Refresh and try again.')
        setSettings(toSettings(data))
        setNotificationPreferences(data.notifications)
        setPrivacy(data.privacy)
        setEtag(responseEtag)
        onBusinessUpdated(data.business)
      }).catch((error: unknown) => {
        if (active) setLoadError(error instanceof Error ? error.message : 'Workspace settings could not be loaded.')
      }).finally(() => { if (active) setLoading(false) }),
      apiRequest<MemberApi[]>(businessPath(businessId, '/members')).then((members) => {
        if (active) setTeam(members.map((member) => {
          const displayName = member.display_name?.trim() || member.email?.trim() || `Team member ${member.user_id.slice(0, 8)}`
          return {
            id: member.id,
            name: displayName,
            email: member.email?.trim() || 'Email unavailable',
            role: member.role,
            initials: initialsFor(displayName),
          }
        }))
      }).catch((error: unknown) => {
        if (active) setTeamError(error instanceof Error ? error.message : 'Workspace members could not be loaded.')
      }).finally(() => { if (active) setTeamLoading(false) }),
    ])
    return () => { active = false }
  }, [businessId, onBusinessUpdated])

  function updateField(field: keyof BusinessSettings, value: string) {
    setSettings((current) => ({ ...current, [field]: value }))
    setSaveMessage('')
  }

  async function saveSettings(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!etag || saving || !canManage) return
    setSaving(true)
    try {
      const { data, headers } = await apiRequestWithHeaders<SettingsApi>(businessPath(businessId, '/settings'), {
        method: 'PATCH',
        headers: { 'If-Match': etag },
        body: JSON.stringify({
          name: settings.businessName.trim(),
          support_email: settings.supportEmail.trim() || null,
          phone: settings.phone.trim() || null,
          website: settings.website.trim() || null,
          country: settings.country || null,
          currency: settings.currency,
          timezone: settings.timezone,
          return_policy: settings.returnPolicy || null,
          delivery_policy: settings.deliveryPolicy || null,
        }),
      })
      setSettings(toSettings(data))
      setNotificationPreferences(data.notifications)
      setPrivacy(data.privacy)
      setEtag(headers.get('ETag'))
      onBusinessUpdated(data.business)
      setSaveMessage('Business profile saved.')
      notify('Business profile saved')
    } catch (error) {
      setSaveMessage(error instanceof Error ? error.message : 'Business profile could not be saved.')
    } finally {
      setSaving(false)
    }
  }

  async function inviteMember(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!canManage) return
    setInviting(true)
    setInviteError('')
    try {
      const invitation = await apiRequest<InvitationApi>(businessPath(businessId, '/invitations'), {
        method: 'POST',
        body: JSON.stringify({ email: inviteEmail.trim().toLowerCase(), role: inviteRole }),
      })
      setInviteEmail('')
      notify(`Invitation sent to ${invitation.email}`)
    } catch (error) {
      setInviteError(error instanceof Error ? error.message : 'The invitation could not be sent.')
    } finally {
      setInviting(false)
    }
  }

  async function removeMember(member: TeamMember) {
    if (business.role !== 'owner' || !window.confirm(`Remove ${member.name} from this workspace?`)) return
    try {
      await apiRequest(businessPath(businessId, `/members/${encodeURIComponent(member.id)}`), { method: 'DELETE' })
      setTeam((members) => members.filter((item) => item.id !== member.id))
      notify(`${member.name} was removed from the workspace`)
    } catch (error) {
      setTeamError(error instanceof Error ? error.message : 'The workspace member could not be removed.')
    }
  }

  async function saveNotifications() {
    if (!etag || saving || !canManage) return
    setSaving(true)
    try {
      const { data, headers } = await apiRequestWithHeaders<SettingsApi>(businessPath(businessId, '/settings'), {
        method: 'PATCH',
        headers: { 'If-Match': etag },
        body: JSON.stringify({ notifications: notificationPreferences }),
      })
      setNotificationPreferences(data.notifications)
      setSettings(toSettings(data))
      setPrivacy(data.privacy)
      setEtag(headers.get('ETag'))
      onBusinessUpdated(data.business)
      notify('Notification preferences saved')
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : 'Notification preferences could not be saved.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="page-body settings-page">
      <div className="page-heading settings-page-heading">
        <div>
          <h1>Settings</h1>
          <p>Manage your business, team, and workspace preferences.</p>
        </div>
        {activeTab === 'Business profile' && <Button type="submit" form="business-settings-form" disabled={loading || saving || !etag || !canManage}><Check size={16} /> {saving ? 'Saving...' : 'Save changes'}</Button>}
      </div>
      <div className="settings-layout">
        <nav className="settings-nav" aria-label="Settings sections">
          <p className="settings-nav-title">Workspace settings</p>
          {tabs.map(({ label, icon: IconComponent }) => (
            <button type="button" className={`settings-nav-item ${activeTab === label ? 'settings-nav-active' : ''}`} key={label} onClick={() => setActiveTab(label)} aria-current={activeTab === label ? 'page' : undefined}>
              <IconComponent size={18} />
              <span>{label}</span>
            </button>
          ))}
          <div className="settings-nav-note"><Storefront size={16} /><span>Changes here apply to the selected business workspace.</span></div>
        </nav>
        <div className="settings-content">
          {loadError && <div className="settings-inline-error" role="alert"><WarningCircle size={16} />{loadError}</div>}
          {loading && <p className="settings-help-text" role="status">Loading workspace settings...</p>}
          {activeTab === 'Business profile' && (
            <form id="business-settings-form" className="settings-form" onSubmit={saveSettings}>
              <fieldset className="settings-fieldset" disabled={!canManage || loading}>
              <SettingsSection title="Business information" description="Details your team and agent use to represent your business.">
                <div className="settings-field-grid">
                  <SettingsField label="Business name" id="settings-business-name" value={settings.businessName} onChange={(value) => updateField('businessName', value)} required />
                  <SettingsField label="Customer support email" id="settings-support-email" type="email" value={settings.supportEmail} onChange={(value) => updateField('supportEmail', value)} required />
                  <SettingsField label="Business phone" id="settings-phone" type="tel" value={settings.phone} onChange={(value) => updateField('phone', value)} />
                  <SettingsField label="Website" id="settings-website" type="url" value={settings.website} onChange={(value) => updateField('website', value)} />
                </div>
              </SettingsSection>
              <SettingsSection title="Regional preferences" description="Set the formats used for orders and business hours.">
                <div className="settings-field-grid">
                  <SettingsSelect label="Country" id="settings-country" value={settings.country} onChange={(value) => updateField('country', value)} options={[{ value: '', label: 'Not set' }, { value: 'GH', label: 'Ghana' }, { value: 'NG', label: 'Nigeria' }, { value: 'KE', label: 'Kenya' }, { value: 'ZA', label: 'South Africa' }, { value: 'GB', label: 'United Kingdom' }, { value: 'US', label: 'United States' }]} />
                  <SettingsSelect label="Currency" id="settings-currency" value={settings.currency} onChange={(value) => updateField('currency', value)} options={['USD', 'GBP', 'GHS', 'NGN', 'KES', 'ZAR'].map((value) => ({ value, label: value }))} />
                  <div className="settings-field settings-field-full">
                    <label htmlFor="settings-timezone">Time zone</label>
                    <select id="settings-timezone" value={settings.timezone} onChange={(event) => updateField('timezone', event.target.value)}>
                      <option value="Africa/Accra">Africa/Accra (GMT)</option>
                      <option value="Africa/Lagos">Africa/Lagos (WAT)</option>
                      <option value="Africa/Nairobi">Africa/Nairobi (EAT)</option>
                      <option value="Africa/Johannesburg">Africa/Johannesburg (SAST)</option>
                      <option value="Europe/London">Europe/London</option>
                      <option value="America/New_York">America/New York</option>
                    </select>
                    <small>Order times and business hours use this time zone.</small>
                  </div>
                </div>
              </SettingsSection>
              <SettingsSection title="Customer policies" description="Your agent uses these policies when answering customer questions.">
                <div className="settings-field settings-field-full">
                  <label htmlFor="settings-delivery-policy">Delivery policy</label>
                  <textarea id="settings-delivery-policy" rows={3} value={settings.deliveryPolicy} onChange={(event) => updateField('deliveryPolicy', event.target.value)} />
                  <small>Only include delivery details you can confirm.</small>
                </div>
                <div className="settings-field settings-field-full">
                  <label htmlFor="settings-return-policy">Returns and refunds</label>
                  <textarea id="settings-return-policy" rows={3} value={settings.returnPolicy} onChange={(event) => updateField('returnPolicy', event.target.value)} />
                  <small>Your agent will share this policy and hand off exceptions to your team.</small>
                </div>
              </SettingsSection>
              </fieldset>
              {saveMessage && <p className="settings-save-message" role="status">{saveMessage}</p>}
              {!canManage && <p className="settings-help-text">Only workspace owners and admins can update business settings.</p>}
            </form>
          )}
          {activeTab === 'Team' && (
            <div className="settings-section-stack">
              <SettingsSection title="Workspace members" description="Invite teammates and choose the access they need.">
                <form className="invite-form" onSubmit={inviteMember}>
                  <fieldset className="settings-fieldset" disabled={!canManage || inviting}>
                  <div className="invite-fields">
                    <div className="settings-field">
                      <label htmlFor="invite-email">Email address</label>
                      <input id="invite-email" type="email" autoComplete="email" placeholder="teammate@business.com" value={inviteEmail} onChange={(event) => { setInviteEmail(event.target.value); setInviteError('') }} required />
                    </div>
                    <div className="settings-field">
                      <label htmlFor="invite-role">Role</label>
                      <select id="invite-role" value={inviteRole} onChange={(event) => setInviteRole(event.target.value as typeof inviteRole)}>
                        <option value="staff">Staff</option><option value="admin">Admin</option><option value="read_only">Read only</option>
                      </select>
                    </div>
                    <Button type="submit"><Plus size={16} /> {inviting ? 'Sending...' : 'Send invite'}</Button>
                  </div>
                  </fieldset>
                  {inviteError && <p className="settings-form-error" role="alert">{inviteError}</p>}
                  <p className="settings-help-text">An invitation email will be sent to the address above.</p>
                  {!canManage && <p className="settings-help-text">Only workspace owners and admins can invite teammates.</p>}
                </form>
                <div className="team-list">
                  {team.map((member) => (
                    <div className="team-row" key={member.email}>
                      <span className="team-avatar">{member.initials}</span>
                      <span className="team-person"><strong>{member.name}</strong><small>{member.email}</small></span>
                      <Badge color={member.role === 'owner' ? 'green' : 'gray'} variant="soft">{roleLabel(member.role)}</Badge>
                      {business.role === 'owner' && member.role !== 'owner' && <button className="team-remove" type="button" aria-label={`Remove ${member.name}`} onClick={() => { void removeMember(member) }}><Trash size={16} /></button>}
                    </div>
                  ))}
                  {teamLoading && <p className="settings-help-text">Loading workspace members...</p>}
                  {!teamLoading && !teamError && team.length === 0 && <p className="settings-help-text">No workspace members were returned.</p>}
                  {teamError && <p className="settings-form-error" role="alert">{teamError}</p>}
                </div>
              </SettingsSection>
              <SettingsSection title="Role access" description="Use the least access needed for each role.">
                <div className="role-descriptions">
                  <RoleDescription name="Owner" text="Full workspace access, billing, and team management." />
                  <RoleDescription name="Admin" text="Manage integrations, agent settings, and team members." />
                  <RoleDescription name="Staff" text="Respond to conversations and manage orders." />
                  <RoleDescription name="Read only" text="View conversations and orders without making changes." />
                </div>
              </SettingsSection>
            </div>
          )}
          {activeTab === 'Notifications' && (
            <SettingsSection title="Workspace notifications" description="Choose which workspace updates appear for you and your team.">
              <div className="notification-preferences">
                <NotificationPreference label="New customer conversations" description="Get notified when a conversation needs your team." checked={notificationPreferences.new_conversations} onChange={(checked) => setNotificationPreferences((current) => ({ ...current, new_conversations: checked }))} />
                <NotificationPreference label="Approval requests" description="Know when the agent needs approval for an action." checked={notificationPreferences.approval_requests} onChange={(checked) => setNotificationPreferences((current) => ({ ...current, approval_requests: checked }))} />
                <NotificationPreference label="PayPal payment updates" description="Get notified when a payment is verified or needs attention." checked={notificationPreferences.payment_updates} onChange={(checked) => setNotificationPreferences((current) => ({ ...current, payment_updates: checked }))} />
                <NotificationPreference label="Weekly business summary" description="Receive a weekly summary of conversations and orders." checked={notificationPreferences.weekly_summary} onChange={(checked) => setNotificationPreferences((current) => ({ ...current, weekly_summary: checked }))} />
              </div>
              <div className="notification-save-row"><span>Changes apply to this workspace.</span><Button type="button" variant="soft" disabled={loading || saving || !etag} onClick={() => { void saveNotifications() }}><Check size={15} /> {saving ? 'Saving...' : 'Save preferences'}</Button></div>
            </SettingsSection>
          )}
          {activeTab === 'Data & privacy' && (
            <div className="settings-section-stack">
              <SettingsSection title="Connected business data" description="Understand which systems provide business facts to Reactant.">
                {integrations.length === 0 && <p className="settings-help-text">No business systems are connected.</p>}
                {integrations.map((integration) => (
                  <div className="data-source-row" key={integration.id}>
                    <span className="data-source-icon"><Storefront size={18} /></span>
                    <span><strong>{integration.provider[0].toUpperCase() + integration.provider.slice(1)}</strong><small>{integration.last_error ?? integration.category}</small></span>
                    <Badge color={integration.status === 'connected' ? 'green' : integration.status === 'pending' ? 'orange' : 'gray'} variant="soft">{integration.status}</Badge>
                  </div>
                ))}
              </SettingsSection>
              <SettingsSection title="Privacy policy" description="Workspace privacy and retention metadata returned by Reactant.">
                {Object.entries(privacy).length > 0
                  ? Object.entries(privacy).map(([key, value]) => <div className="privacy-control" key={key}><span className="privacy-icon"><Database size={18} /></span><div><strong>{key.replaceAll('_', ' ')}</strong><small>{value === null ? 'Not set' : String(value)}</small></div></div>)
                  : <p className="settings-help-text">No additional privacy metadata is configured for this workspace.</p>}
                <div className="privacy-control"><span className="privacy-icon"><Globe size={18} /></span><div><strong>Connected accounts</strong><small>Review connection health and revoke access in Integrations.</small></div><Button variant="soft" color="gray" onClick={openIntegrations}>Open integrations</Button></div>
              </SettingsSection>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function SettingsSection({ title, description, children }: { title: string; description: string; children: React.ReactNode }) {
  return (
    <section className="panel settings-card">
      <div className="settings-card-heading"><h2>{title}</h2><p>{description}</p></div>
      <div className="settings-card-content">{children}</div>
    </section>
  )
}

function SettingsField({ label, id, value, onChange, type = 'text', required }: { label: string; id: string; value: string; onChange: (value: string) => void; type?: string; required?: boolean }) {
  return <div className="settings-field"><label htmlFor={id}>{label}</label><input id={id} type={type} value={value} onChange={(event) => onChange(event.target.value)} required={required} /></div>
}

function SettingsSelect({ label, id, value, options, onChange }: { label: string; id: string; value: string; options: { value: string; label: string }[]; onChange: (value: string) => void }) {
  return <div className="settings-field"><label htmlFor={id}>{label}</label><select id={id} value={value} onChange={(event) => onChange(event.target.value)}>{options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></div>
}

function RoleDescription({ name, text }: { name: string; text: string }) {
  return <div className="role-description"><strong>{name}</strong><span>{text}</span></div>
}

function NotificationPreference({ label, description, checked, onChange }: { label: string; description: string; checked: boolean; onChange: (checked: boolean) => void }) {
  return <div className="notification-preference"><span><strong>{label}</strong><small>{description}</small></span><Switch checked={checked} onCheckedChange={onChange} aria-label={label} /></div>
}
