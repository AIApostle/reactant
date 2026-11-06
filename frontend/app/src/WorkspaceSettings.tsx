import { useState } from 'react'
import {
  Bell,
  BuildingOffice,
  Check,
  CreditCard,
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
  name: string
  email: string
  role: 'Owner' | 'Admin' | 'Staff' | 'Read only'
  initials: string
}

const settingsKey = 'reactant-business-settings'
const defaultSettings: BusinessSettings = {
  businessName: 'Olive & Oak Studio',
  supportEmail: 'hello@oliveandoak.example',
  phone: '+233 20 000 0000',
  website: 'https://oliveandoak.example',
  country: 'Ghana',
  currency: 'USD',
  timezone: 'Africa/Accra',
  returnPolicy: 'Unused items can be returned within 14 days of delivery. Customers should contact our team before sending a return.',
  deliveryPolicy: 'We deliver across Ghana. Delivery fees and estimated arrival dates are confirmed at checkout.',
}

const initialTeam: TeamMember[] = [
  { name: 'Ada Okafor', email: 'ada@oliveandoak.example', role: 'Owner', initials: 'AO' },
  { name: 'Kofi Mensah', email: 'kofi@oliveandoak.example', role: 'Staff', initials: 'KM' },
]

const tabs: { label: SettingsTab; icon: Icon }[] = [
  { label: 'Business profile', icon: BuildingOffice },
  { label: 'Team', icon: UsersThree },
  { label: 'Notifications', icon: Bell },
  { label: 'Data & privacy', icon: ShieldCheck },
]

function readSettings(): { settings: BusinessSettings; error: string } {
  try {
    const stored = window.localStorage.getItem(settingsKey)
    if (!stored) return { settings: defaultSettings, error: '' }
    const parsed: unknown = JSON.parse(stored)
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      return { settings: defaultSettings, error: 'Saved business settings could not be read. The default preview values are shown.' }
    }
    return { settings: { ...defaultSettings, ...parsed }, error: '' }
  } catch {
    return { settings: defaultSettings, error: 'Saved business settings could not be read. The default preview values are shown.' }
  }
}

export default function WorkspaceSettings({ notify, paymentConnected }: { notify: (message: string) => void; paymentConnected: boolean }) {
  const [loadedSettings] = useState(readSettings)
  const [settings, setSettings] = useState(loadedSettings.settings)
  const [activeTab, setActiveTab] = useState<SettingsTab>('Business profile')
  const [saveMessage, setSaveMessage] = useState(loadedSettings.error)
  const [team, setTeam] = useState(initialTeam)
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState<TeamMember['role']>('Staff')
  const [inviteError, setInviteError] = useState('')
  const [notificationPreferences, setNotificationPreferences] = useState({
    newConversations: true,
    approvalRequests: true,
    paymentUpdates: true,
    weeklySummary: false,
  })

  function updateField(field: keyof BusinessSettings, value: string) {
    setSettings((current) => ({ ...current, [field]: value }))
    setSaveMessage('')
  }

  function saveSettings(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    try {
      window.localStorage.setItem(settingsKey, JSON.stringify(settings))
      setSaveMessage('Business profile saved in this browser.')
      notify('Business profile saved')
    } catch {
      setSaveMessage('Could not save this preview in your browser. Check storage permissions and try again.')
    }
  }

  function inviteMember(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const email = inviteEmail.trim().toLowerCase()
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      setInviteError('Enter a valid email address.')
      return
    }
    if (team.some((member) => member.email.toLowerCase() === email)) {
      setInviteError('This person is already in your workspace.')
      return
    }
    const name = email.split('@')[0].replace(/[._-]+/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
    const initials = name.split(' ').map((part) => part[0]).slice(0, 2).join('').toUpperCase()
    setTeam((members) => [...members, { name, email, role: inviteRole, initials }])
    setInviteEmail('')
    setInviteError('')
    notify('Team member added to this preview')
  }

  function removeMember(email: string) {
    setTeam((members) => members.filter((member) => member.email !== email))
    notify('Team member removed from this preview')
  }

  return (
    <div className="page-body settings-page">
      <div className="page-heading settings-page-heading">
        <div>
          <Badge className="preview-data-label" color="gray" variant="soft" radius="full">Sample data</Badge>
          <h1>Settings</h1>
          <p>Manage your business, team, and workspace preferences.</p>
        </div>
        {activeTab === 'Business profile' && <Button type="submit" form="business-settings-form"><Check size={16} /> Save changes</Button>}
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
          {loadedSettings.error && <div className="settings-inline-error" role="alert"><WarningCircle size={16} />{loadedSettings.error}</div>}
          {activeTab === 'Business profile' && (
            <form id="business-settings-form" className="settings-form" onSubmit={saveSettings}>
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
                  <SettingsSelect label="Country" id="settings-country" value={settings.country} onChange={(value) => updateField('country', value)} options={['Ghana', 'Nigeria', 'Kenya', 'South Africa', 'United Kingdom', 'United States']} />
                  <SettingsSelect label="Currency" id="settings-currency" value={settings.currency} onChange={(value) => updateField('currency', value)} options={['USD', 'GBP', 'GHS', 'NGN', 'KES', 'ZAR']} />
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
              {saveMessage && <p className="settings-save-message" role="status">{saveMessage}</p>}
              <p className="settings-preview-note"><WarningCircle size={15} /> Settings save to this browser preview. They are not yet sent to a backend.</p>
            </form>
          )}
          {activeTab === 'Team' && (
            <div className="settings-section-stack">
              <SettingsSection title="Workspace members" description="Invite teammates and choose the access they need.">
                <form className="invite-form" onSubmit={inviteMember}>
                  <div className="invite-fields">
                    <div className="settings-field">
                      <label htmlFor="invite-email">Email address</label>
                      <input id="invite-email" type="email" autoComplete="email" placeholder="teammate@business.com" value={inviteEmail} onChange={(event) => { setInviteEmail(event.target.value); setInviteError('') }} required />
                    </div>
                    <div className="settings-field">
                      <label htmlFor="invite-role">Role</label>
                      <select id="invite-role" value={inviteRole} onChange={(event) => setInviteRole(event.target.value as TeamMember['role'])}>
                        <option>Staff</option><option>Admin</option><option>Read only</option>
                      </select>
                    </div>
                    <Button type="submit"><Plus size={16} /> Add member</Button>
                  </div>
                  {inviteError && <p className="settings-form-error" role="alert">{inviteError}</p>}
                  <p className="settings-help-text">Preview only. This adds a sample member to this screen; no email invitation is sent.</p>
                </form>
                <div className="team-list">
                  {team.map((member) => (
                    <div className="team-row" key={member.email}>
                      <span className="team-avatar">{member.initials}</span>
                      <span className="team-person"><strong>{member.name}</strong><small>{member.email}</small></span>
                      <Badge color={member.role === 'Owner' ? 'green' : 'gray'} variant="soft">{member.role}</Badge>
                      {member.role !== 'Owner' && <button className="team-remove" type="button" aria-label={`Remove ${member.name}`} onClick={() => removeMember(member.email)}><Trash size={16} /></button>}
                    </div>
                  ))}
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
            <SettingsSection title="Email notifications" description="Choose the updates you and your team receive.">
              <div className="notification-preferences">
                <NotificationPreference label="New customer conversations" description="Get notified when a conversation needs your team." checked={notificationPreferences.newConversations} onChange={(checked) => setNotificationPreferences((current) => ({ ...current, newConversations: checked }))} />
                <NotificationPreference label="Approval requests" description="Know when the agent needs approval for an action." checked={notificationPreferences.approvalRequests} onChange={(checked) => setNotificationPreferences((current) => ({ ...current, approvalRequests: checked }))} />
                <NotificationPreference label="PayPal payment updates" description="Get notified when a payment is verified or needs attention." checked={notificationPreferences.paymentUpdates} onChange={(checked) => setNotificationPreferences((current) => ({ ...current, paymentUpdates: checked }))} />
                <NotificationPreference label="Weekly business summary" description="Receive a weekly summary of conversations and orders." checked={notificationPreferences.weeklySummary} onChange={(checked) => setNotificationPreferences((current) => ({ ...current, weeklySummary: checked }))} />
              </div>
              <div className="notification-save-row"><span>Notification preferences are local to this preview.</span><Button variant="soft" onClick={() => notify('Notification preferences saved in this preview')}><Check size={15} /> Save preferences</Button></div>
            </SettingsSection>
          )}
          {activeTab === 'Data & privacy' && (
            <div className="settings-section-stack">
              <SettingsSection title="Connected business data" description="Understand which systems provide business facts to Reactant.">
                <div className="data-source-row"><span className="data-source-icon"><Storefront size={18} /></span><span><strong>WooCommerce catalog</strong><small>Product, variant, and inventory data</small></span><Badge color="green" variant="soft">Connected</Badge></div>
                <div className="data-source-row"><span className="data-source-icon"><CreditCard size={18} /></span><span><strong>PayPal</strong><small>Checkout and verified payment status</small></span><Badge color={paymentConnected ? 'green' : 'gray'} variant="soft">{paymentConnected ? 'Connected' : 'Not connected'}</Badge></div>
              </SettingsSection>
              <SettingsSection title="Privacy controls" description="Keep control of your workspace and connected business data.">
                <div className="privacy-control"><span className="privacy-icon"><Database size={18} /></span><div><strong>Conversation and agent history</strong><small>Review your business data retention and deletion options.</small></div><Button variant="soft" color="gray" onClick={() => notify('Data controls will be available when account services are connected')}>Review</Button></div>
                <div className="privacy-control"><span className="privacy-icon"><Globe size={18} /></span><div><strong>Connected accounts</strong><small>Revoke a store or channel connection at any time.</small></div><Button variant="soft" color="gray" onClick={() => notify('Manage connected accounts in Integrations')}>Manage</Button></div>
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

function SettingsSelect({ label, id, value, options, onChange }: { label: string; id: string; value: string; options: string[]; onChange: (value: string) => void }) {
  return <div className="settings-field"><label htmlFor={id}>{label}</label><select id={id} value={value} onChange={(event) => onChange(event.target.value)}>{options.map((option) => <option key={option}>{option}</option>)}</select></div>
}

function RoleDescription({ name, text }: { name: string; text: string }) {
  return <div className="role-description"><strong>{name}</strong><span>{text}</span></div>
}

function NotificationPreference({ label, description, checked, onChange }: { label: string; description: string; checked: boolean; onChange: (checked: boolean) => void }) {
  return <div className="notification-preference"><span><strong>{label}</strong><small>{description}</small></span><Switch checked={checked} onCheckedChange={onChange} aria-label={label} /></div>
}
