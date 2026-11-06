import { useEffect, useMemo, useState } from 'react'
import {
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  Bell,
  CaretDown,
  CaretRight,
  Check,
  CheckCircle,
  ChatCircleDots,
  Clock,
  CreditCard,
  DotsThree,
  Funnel,
  GearSix,
  House,
  ImageSquare,
  MagnifyingGlass,
  List,
  Package,
  PaperPlaneTilt,
  Plus,
  Robot,
  ShieldCheck,
  ShoppingBagOpen,
  Storefront,
  Trash,
  TelegramLogo,
  UploadSimple,
  WarningCircle,
  X,
  type Icon,
} from '@phosphor-icons/react'
import {
  Badge,
  Button,
  Dialog,
  Switch,
  TextField,
  Theme,
} from '@radix-ui/themes'
import WorkspaceSettings from './WorkspaceSettings'
import BrandMark from './BrandMark'
import './App.css'

type Page = 'overview' | 'inbox' | 'catalog' | 'orders' | 'approvals' | 'integrations' | 'agent' | 'owner-assistant' | 'settings'
type Connection = 'WooCommerce' | 'Telegram' | 'PayPal' | 'Shopify' | 'WhatsApp'
type ConversationStatus = 'Needs reply' | 'Open' | 'Resolved'

type Conversation = {
  id: string
  name: string
  initials: string
  color: string
  channel: string
  preview: string
  time: string
  status: ConversationStatus
  unread: boolean
  messages: { from: 'customer' | 'agent' | 'staff'; text: string; time: string }[]
}

type Order = {
  id: string
  customer: string
  initials: string
  item: string
  date: string
  total: number
  status: 'Paid' | 'Pending payment' | 'Processing' | 'Cancelled'
  email: string
}

type CatalogProduct = {
  id: string
  name: string
  description: string
  category: string
  price: number
  stock: number | null
  images: string[]
  available: boolean
  agentCanShare: boolean
}

function formatCurrency(amount: number) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(amount)
}

const initialConversations: Conversation[] = [
  {
    id: 'C-2048',
    name: 'Ama Mensah',
    initials: 'AM',
    color: 'coral',
    channel: 'Telegram',
    preview: 'Do you have the linen set in sand?',
    time: '2 min',
    status: 'Needs reply',
    unread: true,
    messages: [
      { from: 'customer', text: 'Hi, I saw the linen bedding set on your store.', time: '10:42 AM' },
      { from: 'agent', text: 'Hello Ama! The Coastline Linen Set is available in Queen and King sizes. Which size are you looking for?', time: '10:42 AM' },
      { from: 'customer', text: 'Do you have the linen set in sand?', time: '10:44 AM' },
    ],
  },
  {
    id: 'C-2047',
    name: 'Kojo Boateng',
    initials: 'KB',
    color: 'blue',
    channel: 'Telegram',
    preview: 'Thanks, I will take the walnut one.',
    time: '18 min',
    status: 'Open',
    unread: false,
    messages: [
      { from: 'customer', text: 'Could you share more about the walnut serving board?', time: '10:12 AM' },
      { from: 'agent', text: 'It is made from solid walnut and is currently in stock. I can help you add one to your cart.', time: '10:13 AM' },
      { from: 'customer', text: 'Thanks, I will take the walnut one.', time: '10:26 AM' },
    ],
  },
  {
    id: 'C-2046',
    name: 'Esi Owusu',
    initials: 'EO',
    color: 'violet',
    channel: 'Telegram',
    preview: 'Can someone help with delivery?',
    time: '42 min',
    status: 'Needs reply',
    unread: true,
    messages: [
      { from: 'customer', text: 'I placed an order yesterday but I am not sure when it will arrive.', time: '9:51 AM' },
      { from: 'agent', text: 'I can ask our team to check the delivery details for you.', time: '9:52 AM' },
      { from: 'customer', text: 'Can someone help with delivery?', time: '9:53 AM' },
    ],
  },
  {
    id: 'C-2044',
    name: 'Nana Asare',
    initials: 'NA',
    color: 'green',
    channel: 'Telegram',
    preview: 'That answers everything, thank you.',
    time: '1 hr',
    status: 'Resolved',
    unread: false,
    messages: [
      { from: 'customer', text: 'What is your return policy for the ceramic pieces?', time: '9:04 AM' },
      { from: 'agent', text: 'Unused items can be returned within 14 days. I can share the full policy if you need it.', time: '9:05 AM' },
      { from: 'customer', text: 'That answers everything, thank you.', time: '9:08 AM' },
    ],
  },
  {
    id: 'C-2042',
    name: 'Abena Kusi',
    initials: 'AK',
    color: 'gold',
    channel: 'Telegram',
    preview: 'Is the lamp dimmable?',
    time: '2 hrs',
    status: 'Open',
    unread: false,
    messages: [
      { from: 'customer', text: 'Is the woven table lamp dimmable?', time: '8:13 AM' },
      { from: 'agent', text: 'Let me check the product details for you.', time: '8:13 AM' },
    ],
  },
]

const initialOrders: Order[] = [
  { id: 'RA-2084', customer: 'Nana Asare', initials: 'NA', item: 'Coastline Linen Set · Queen', date: 'Today, 10:28 AM', total: 1450, status: 'Paid', email: 'nana.asare@example.com' },
  { id: 'RA-2083', customer: 'Kojo Boateng', initials: 'KB', item: 'Walnut Serving Board', date: 'Today, 10:16 AM', total: 385, status: 'Processing', email: 'kojo.boateng@example.com' },
  { id: 'RA-2082', customer: 'Ama Mensah', initials: 'AM', item: 'Ceramic Pour-over Set', date: 'Today, 9:42 AM', total: 620, status: 'Pending payment', email: 'ama.mensah@example.com' },
  { id: 'RA-2081', customer: 'Kweku Addo', initials: 'KA', item: 'Woven Table Lamp', date: 'Yesterday, 4:18 PM', total: 890, status: 'Paid', email: 'kweku.addo@example.com' },
  { id: 'RA-2080', customer: 'Abena Kusi', initials: 'AK', item: 'Coastline Linen Set · King', date: 'Yesterday, 2:05 PM', total: 1750, status: 'Cancelled', email: 'abena.kusi@example.com' },
]

const navigation: { label: string; page: Page; icon: Icon }[] = [
  { label: 'Overview', page: 'overview', icon: House },
  { label: 'Inbox', page: 'inbox', icon: ChatCircleDots },
  { label: 'Catalog', page: 'catalog', icon: Package },
  { label: 'Orders', page: 'orders', icon: ShoppingBagOpen },
  { label: 'Approvals', page: 'approvals', icon: ShieldCheck },
  { label: 'Integrations', page: 'integrations', icon: Storefront },
  { label: 'Business agent', page: 'agent', icon: Robot },
  { label: 'Agent messages', page: 'owner-assistant', icon: ChatCircleDots },
  { label: 'Settings', page: 'settings', icon: GearSix },
]

const pageTitles: Record<Page, string> = {
  overview: 'Overview',
  inbox: 'Inbox',
  catalog: 'Catalog',
  orders: 'Orders',
  approvals: 'Approvals',
  integrations: 'Integrations',
  agent: 'Business agent',
  'owner-assistant': 'Agent messages',
  settings: 'Settings',
}

function App() {
  const [page, setPage] = useState<Page>('overview')
  const [conversations, setConversations] = useState(initialConversations)
  const [selectedConversation, setSelectedConversation] = useState(initialConversations[0].id)
  const [orders, setOrders] = useState(initialOrders)
  const [catalogProducts, setCatalogProducts] = useState<CatalogProduct[]>([])
  const [pendingApprovals, setPendingApprovals] = useState(2)
  const [selectedOrder, setSelectedOrder] = useState<string | null>(null)
  const [connections, setConnections] = useState<Record<Connection, boolean>>({
    WooCommerce: true,
    Telegram: true,
    PayPal: false,
    Shopify: false,
    WhatsApp: false,
  })
  const [agentEnabled, setAgentEnabled] = useState(true)
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const [connectionDialog, setConnectionDialog] = useState<Connection | null>(null)
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchTerm, setSearchTerm] = useState('')
  const [reply, setReply] = useState('')
  const [toast, setToast] = useState('')
  const [conversationFilter, setConversationFilter] = useState<'All' | ConversationStatus>('All')
  const [orderFilter, setOrderFilter] = useState('All orders')

  const currentConversation = conversations.find((item) => item.id === selectedConversation) ?? conversations[0]
  const activeOrder = orders.find((item) => item.id === selectedOrder)

  useEffect(() => {
    if (!toast) return
    const timeout = window.setTimeout(() => setToast(''), 2800)
    return () => window.clearTimeout(timeout)
  }, [toast])

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setSearchOpen(true)
      }
      if (event.key === 'Escape') setMobileNavOpen(false)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  function navigate(nextPage: Page) {
    setPage(nextPage)
    setMobileNavOpen(false)
    setSelectedOrder(null)
  }

  function sendReply(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!reply.trim()) return
    setConversations((items) =>
      items.map((item) =>
        item.id === selectedConversation
          ? {
              ...item,
              preview: reply.trim(),
              time: 'now',
              status: 'Open',
              messages: [...item.messages, { from: 'staff', text: reply.trim(), time: 'Now' }],
            }
          : item,
      ),
    )
    setReply('')
    setToast('Reply sent in this preview')
  }

  function setConversationStatus(id: string, status: ConversationStatus) {
    setConversations((items) => items.map((item) => item.id === id ? { ...item, status, unread: false } : item))
    setToast(status === 'Resolved' ? 'Conversation marked as resolved' : 'Conversation reopened')
  }

  function decideApproval(orderId: string, decision: 'approve' | 'reject') {
    setOrders((items) =>
      items.map((item) =>
        item.id === orderId ? { ...item, status: decision === 'approve' ? 'Pending payment' : 'Cancelled' } : item,
      ),
    )
    setPendingApprovals((count) => Math.max(0, count - 1))
    setToast(decision === 'approve' ? 'Approval recorded in this preview' : 'Request declined in this preview')
  }

  function resolveHandoffApproval() {
    setPendingApprovals((count) => Math.max(0, count - 1))
    setToast('Handoff reviewed in this preview')
  }

  const visibleConversations = useMemo(() => conversations.filter((conversation) => {
    const matchesStatus = conversationFilter === 'All' || conversation.status === conversationFilter
    const matchesSearch = `${conversation.name} ${conversation.preview} ${conversation.id}`.toLowerCase().includes(searchTerm.toLowerCase())
    return matchesStatus && matchesSearch
  }), [conversationFilter, conversations, searchTerm])

  const visibleOrders = useMemo(() => orders.filter((order) => {
    const matchesStatus = orderFilter === 'All orders' || order.status === orderFilter
    const matchesSearch = `${order.customer} ${order.id} ${order.item}`.toLowerCase().includes(searchTerm.toLowerCase())
    return matchesStatus && matchesSearch
  }), [orderFilter, orders, searchTerm])

  const globalResults = useMemo(() => {
    const term = searchTerm.toLowerCase().trim()
    if (!term) return { conversations: [], orders: [], pages: [] as typeof navigation }
    return {
      conversations: conversations.filter((item) => `${item.name} ${item.preview} ${item.id}`.toLowerCase().includes(term)).slice(0, 3),
      orders: orders.filter((item) => `${item.customer} ${item.id} ${item.item}`.toLowerCase().includes(term)).slice(0, 3),
      pages: navigation.filter((item) => item.label.toLowerCase().includes(term)).slice(0, 4),
    }
  }, [conversations, orders, searchTerm])

  function completeConnection(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!connectionDialog) return
    setConnections((items) => ({ ...items, [connectionDialog]: true }))
    setToast(`${connectionDialog} connected in this preview`)
    setConnectionDialog(null)
  }

  function createPreviewOrder(customer: string, item: string, total: number) {
    const nameParts = customer.trim().split(/\s+/)
    const initials = nameParts.slice(0, 2).map((part) => part[0]).join('').toUpperCase()
    const emailName = customer.trim().toLowerCase().replace(/[^a-z0-9]+/g, '.').replace(/^\.+|\.+$/g, '')
    setOrders((items) => [{
      id: `RA-${String(Date.now()).slice(-4)}`,
      customer: customer.trim(),
      initials,
      item: item.trim(),
      date: 'Today, just now',
      total,
      status: 'Pending payment',
      email: `${emailName || 'customer'}@example.com`,
    }, ...items])
    setSelectedOrder(null)
    setToast('Sample order created in this preview')
  }

  function openConversation(id: string) {
    setSelectedConversation(id)
    setPage('inbox')
    setConversations((items) => items.map((item) => item.id === id ? { ...item, unread: false } : item))
    setSearchOpen(false)
    setSearchTerm('')
  }

  function openOrder(id: string) {
    setSelectedOrder(id)
    setPage('orders')
    setSearchOpen(false)
    setSearchTerm('')
  }

  function openPageFromSearch(nextPage: Page) {
    navigate(nextPage)
    setSearchOpen(false)
    setSearchTerm('')
  }

  return (
    <Theme accentColor="grass" grayColor="slate" radius="medium" scaling="100%" appearance="light">
      <div className="app-shell">
        {mobileNavOpen && <button className="sidebar-scrim" aria-label="Close navigation" onClick={() => setMobileNavOpen(false)} />}
        <Sidebar
          page={page}
          navigate={navigate}
          mobileNavOpen={mobileNavOpen}
          close={() => setMobileNavOpen(false)}
          notify={setToast}
          inboxCount={conversations.filter((conversation) => conversation.unread).length}
          approvalCount={pendingApprovals}
        />
        <div className="workspace">
          <header className="topbar">
            <Button className="mobile-menu" variant="ghost" aria-label="Open navigation" onClick={() => setMobileNavOpen(true)}>
              <List size={21} />
            </Button>
            <div className="breadcrumb">
              <span className="breadcrumb-workspace">Olive & Oak Studio</span>
              <CaretRight size={14} />
              <span>{pageTitles[page]}</span>
              <Badge color="gray" variant="soft" radius="full" className="preview-badge">Preview</Badge>
            </div>
            <div className="topbar-actions">
              <Button variant="surface" className="search-trigger" onClick={() => { setSearchTerm(''); setSearchOpen(true) }}>
                <MagnifyingGlass size={16} />
                <span>Search</span>
                <kbd>⌘ K</kbd>
              </Button>
              <button className="icon-button notification-button" aria-label="Notifications" onClick={() => setToast('You are all caught up')}>
                <Bell size={19} />
                <span className="notification-mark" />
              </button>
              <button className="profile-button" aria-label="Account settings" onClick={() => navigate('settings')}>
                <span className="profile-avatar">AO</span>
                <CaretDown size={14} />
              </button>
            </div>
          </header>

          <main className="main-content">
            {page === 'overview' && (
              <Overview
                agentEnabled={agentEnabled}
                conversations={conversations}
                orders={orders}
                catalogProductCount={catalogProducts.length}
                connections={connections}
                navigate={navigate}
                openConversation={openConversation}
                openOrder={openOrder}
                setConnectionDialog={setConnectionDialog}
                paymentConnected={connections.PayPal}
              />
            )}
            {page === 'inbox' && (
              <Inbox
                conversations={visibleConversations}
                selectedConversation={currentConversation}
                filter={conversationFilter}
                setFilter={setConversationFilter}
                setSearch={setSearchTerm}
                search={searchTerm}
                setSelected={openConversation}
                sendReply={sendReply}
                reply={reply}
                setReply={setReply}
                setStatus={setConversationStatus}
              />
            )}
            {page === 'catalog' && (
              <Catalog
                products={catalogProducts}
                setProducts={setCatalogProducts}
                notify={setToast}
              />
            )}
            {page === 'orders' && (
              <Orders
                orders={visibleOrders}
                selectedOrder={activeOrder}
                filter={orderFilter}
                setFilter={setOrderFilter}
                search={searchTerm}
                setSearch={setSearchTerm}
                selectOrder={(id) => setSelectedOrder(id)}
                createOrder={createPreviewOrder}
              />
            )}
            {page === 'approvals' && <Approvals orders={orders} decide={decideApproval} resolveHandoff={resolveHandoffApproval} pendingCount={pendingApprovals} />}
            {page === 'integrations' && (
              <Integrations connections={connections} setConnectionDialog={setConnectionDialog} />
            )}
            {page === 'agent' && (
              <AgentSettings enabled={agentEnabled} setEnabled={setAgentEnabled} notify={setToast} paymentConnected={connections.PayPal} />
            )}
            {page === 'settings' && <WorkspaceSettings notify={setToast} paymentConnected={connections.PayPal} />}
            {page === 'owner-assistant' && <OwnerAssistant notify={setToast} resolveApproval={resolveHandoffApproval} />}
          </main>
        </div>

        <Dialog.Root open={connectionDialog !== null} onOpenChange={(open) => !open && setConnectionDialog(null)}>
          <Dialog.Content className="dialog-content">
            <Dialog.Title className="dialog-title">Connect {connectionDialog ?? 'an integration'}</Dialog.Title>
            <Dialog.Description className="dialog-description">
              {!connectionDialog
                ? 'Choose an integration to connect.'
                : connectionDialog === 'PayPal'
                ? 'Connect PayPal for customer checkout and payment verification.'
                : `Add your ${connectionDialog} account to Olive & Oak Studio. Credentials stay private to your workspace.`}
            </Dialog.Description>
            <form className="connection-form" onSubmit={completeConnection}>
              {connectionDialog !== 'PayPal' && (
                <label className="field-label" htmlFor="connection-name">
                  {connectionDialog === 'WooCommerce' ? 'Store URL' : connectionDialog === 'Telegram' ? 'Telegram bot token' : connectionDialog === 'Shopify' ? 'Shopify store domain' : 'Business phone number ID'}
                </label>
              )}
              {connectionDialog !== 'PayPal' && (
                <TextField.Root id="connection-name" type={connectionDialog === 'Telegram' ? 'password' : 'text'} placeholder={connectionDialog === 'WooCommerce' ? 'https://yourstore.com' : connectionDialog === 'Shopify' ? 'your-store.myshopify.com' : connectionDialog === 'Telegram' ? 'Paste your bot token' : `Enter ${connectionDialog} details`} required />
              )}
              {connectionDialog === 'WooCommerce' && (
                <>
                  <label className="field-label" htmlFor="connection-secret">REST API consumer key</label>
                  <TextField.Root id="connection-secret" type="password" placeholder="Paste your consumer key" required />
                  <label className="field-label" htmlFor="connection-secret-two">REST API consumer secret</label>
                  <TextField.Root id="connection-secret-two" type="password" placeholder="Paste your consumer secret" required />
                </>
              )}
              {connectionDialog === 'WhatsApp' && (
                <>
                  <label className="field-label" htmlFor="connection-secret">Access token</label>
                  <TextField.Root id="connection-secret" type="password" placeholder="Paste your access token" required />
                </>
              )}
              {connectionDialog === 'PayPal' && (
                <>
                  <p className="form-note">PayPal will be connected through its secure authorization flow. Reactant will only use it to create customer checkout sessions and verify payments. It cannot access your balance or send payouts.</p>
                  <label className="field-label" htmlFor="connection-secret">Environment</label>
                  <select id="connection-secret" className="settings-select" defaultValue="Sandbox">
                    <option>Sandbox</option>
                    <option>Live</option>
                  </select>
                </>
              )}
              <p className="form-note">Preview only. Your entries are not saved and will not be sent to the provider.</p>
              <div className="dialog-actions">
                <Button type="button" variant="soft" color="gray" onClick={() => setConnectionDialog(null)}>Cancel</Button>
                <Button type="submit">{connectionDialog === 'PayPal' ? 'Continue with PayPal' : 'Save connection'}</Button>
              </div>
            </form>
          </Dialog.Content>
        </Dialog.Root>

        <Dialog.Root open={searchOpen} onOpenChange={(open) => setSearchOpen(open)}>
          <Dialog.Content className="search-dialog">
            <Dialog.Title className="sr-only">Search workspace</Dialog.Title>
            <Dialog.Description className="sr-only">Search conversations, orders, and workspace sections.</Dialog.Description>
            <div className="global-search-field">
              <MagnifyingGlass size={19} />
              <input autoFocus value={searchTerm} onChange={(event) => setSearchTerm(event.target.value)} placeholder="Search or jump to a section..." aria-label="Search conversations, orders, and workspace sections" />
              <Dialog.Close className="dialog-close" aria-label="Close search"><X size={17} /></Dialog.Close>
            </div>
            <div className="global-results">
              {!searchTerm && <p className="search-hint">Find a customer or order, or jump to a workspace section.</p>}
              {searchTerm && globalResults.conversations.length === 0 && globalResults.orders.length === 0 && globalResults.pages.length === 0 && (
                <div className="search-empty"><MagnifyingGlass size={20} /><span>No results for “{searchTerm}”</span></div>
              )}
              {globalResults.pages.length > 0 && (
                <section className="result-group">
                  <p className="result-heading">Go to</p>
                  {globalResults.pages.map((item) => {
                    const IconComponent = item.icon
                    return <button className="search-result" key={item.page} onClick={() => openPageFromSearch(item.page)}><span className="order-result-icon"><IconComponent size={17} /></span><span><strong>{item.label}</strong><small>Open {item.label.toLowerCase()}</small></span><CaretRight size={15} /></button>
                  })}
                </section>
              )}
              {!searchTerm && (
                <section className="result-group">
                  <p className="result-heading">Quick links</p>
                  {navigation.slice(1).map((item) => {
                    const IconComponent = item.icon
                    return <button className="search-result" key={item.page} onClick={() => openPageFromSearch(item.page)}><span className="order-result-icon"><IconComponent size={17} /></span><span><strong>{item.label}</strong><small>Open {item.label.toLowerCase()}</small></span><CaretRight size={15} /></button>
                  })}
                </section>
              )}
              {globalResults.conversations.length > 0 && (
                <section className="result-group">
                  <p className="result-heading">Conversations</p>
                  {globalResults.conversations.map((item) => (
                    <button className="search-result" key={item.id} onClick={() => openConversation(item.id)}>
                      <Avatar initials={item.initials} color={item.color} />
                      <span><strong>{item.name}</strong><small>{item.preview}</small></span>
                      <CaretRight size={15} />
                    </button>
                  ))}
                </section>
              )}
              {globalResults.orders.length > 0 && (
                <section className="result-group">
                  <p className="result-heading">Orders</p>
                  {globalResults.orders.map((item) => (
                    <button className="search-result" key={item.id} onClick={() => openOrder(item.id)}>
                      <span className="order-result-icon"><ShoppingBagOpen size={17} /></span>
                      <span><strong>{item.id} · {item.customer}</strong><small>{item.item}</small></span>
                      <CaretRight size={15} />
                    </button>
                  ))}
                </section>
              )}
            </div>
          </Dialog.Content>
        </Dialog.Root>

        {toast && <div className="toast" role="status"><CheckCircle size={18} weight="fill" />{toast}</div>}
      </div>
    </Theme>
  )
}

function Sidebar({ page, navigate, mobileNavOpen, close, notify, inboxCount, approvalCount }: { page: Page; navigate: (page: Page) => void; mobileNavOpen: boolean; close: () => void; notify: (message: string) => void; inboxCount: number; approvalCount: number }) {
  return (
    <aside className={`sidebar ${mobileNavOpen ? 'sidebar-open' : ''}`}>
      <div className="brand-row">
        <BrandMark className="brand-mark" />
        <span className="brand-name">reactant</span>
        <button className="mobile-close" aria-label="Close navigation" onClick={close}><X size={19} /></button>
      </div>
      <button className="workspace-switcher" onClick={() => navigate('overview')}>
        <span className="workspace-avatar">O</span>
        <span className="workspace-name"><strong>Olive & Oak Studio</strong><small>Sample workspace</small></span>
        <CaretDown size={15} />
      </button>
      <nav className="main-navigation" aria-label="Main navigation">
        <p className="nav-section-label">Workspace</p>
        {navigation.slice(0, 5).map((item) => <NavItem key={item.page} item={item} active={page === item.page} navigate={navigate} count={item.page === 'inbox' ? inboxCount : item.page === 'approvals' ? approvalCount : undefined} />)}
        <p className="nav-section-label manage-label">Manage</p>
        {navigation.slice(5).map((item) => <NavItem key={item.page} item={item} active={page === item.page} navigate={navigate} />)}
      </nav>
      <div className="sidebar-bottom">
        <button className="sidebar-help" onClick={() => notify('The help center will be available in the full workspace.')}>
          <span className="help-icon"><ChatCircleDots size={17} /></span>
          <span><strong>Need a hand?</strong><small>Visit the help center</small></span>
          <ArrowUpRight size={14} />
        </button>
        <div className="sidebar-user">
          <span className="user-avatar">AO</span>
          <span className="user-meta"><strong>Ada Okafor</strong><small>Workspace owner</small></span>
          <DotsThree size={20} />
        </div>
      </div>
    </aside>
  )
}

function NavItem({ item, active, navigate, count }: { item: { label: string; page: Page; icon: Icon }; active: boolean; navigate: (page: Page) => void; count?: number }) {
  const IconComponent = item.icon
  return (
    <button className={`nav-item ${active ? 'nav-item-active' : ''}`} onClick={() => navigate(item.page)} aria-current={active ? 'page' : undefined}>
      <IconComponent size={19} weight={active ? 'fill' : 'regular'} />
      <span>{item.label}</span>
      {count !== undefined && count > 0 && <span className={`nav-count ${item.page === 'inbox' && active ? 'nav-count-active' : ''}`}>{count}</span>}
    </button>
  )
}

function PageHeading({ title, description, action, meta }: { title: string; description: string; action?: React.ReactNode; meta?: React.ReactNode }) {
  return (
    <div className="page-heading">
      <div>
        {meta}
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action && <div className="heading-action">{action}</div>}
    </div>
  )
}

function Overview({
  agentEnabled,
  conversations,
  orders,
  catalogProductCount,
  connections,
  navigate,
  openConversation,
  openOrder,
  setConnectionDialog,
  paymentConnected,
}: {
  agentEnabled: boolean
  conversations: Conversation[]
  orders: Order[]
  catalogProductCount: number
  connections: Record<Connection, boolean>
  navigate: (page: Page) => void
  openConversation: (id: string) => void
  openOrder: (id: string) => void
  setConnectionDialog: (connection: Connection) => void
  paymentConnected: boolean
}) {
  const paidOrders = orders.filter((order) => order.status === 'Paid' || order.status === 'Processing').length
  const needsReply = conversations.filter((conversation) => conversation.status === 'Needs reply').length
  const productSourceReady = connections.WooCommerce || catalogProductCount > 0
  const productSourceDescription = catalogProductCount > 0
    ? `${connections.WooCommerce ? 'WooCommerce sync and ' : ''}${catalogProductCount} Reactant catalog ${catalogProductCount === 1 ? 'product' : 'products'}`
    : 'Products synced from WooCommerce'
  const completedSetupSteps = Number(productSourceReady) + Number(connections.Telegram) + Number(paymentConnected)
  const setupComplete = completedSetupSteps === 3
  return (
    <div className="page-body overview-page">
      <PageHeading
        title="Good morning, Ada"
        description="Here’s what’s happening across your business today."
        meta={<Badge className="preview-data-label" color="gray" variant="soft" radius="full">Sample data</Badge>}
        action={<Button onClick={() => navigate('integrations')}><Plus size={17} /> Connect a channel</Button>}
      />

      <section className="metric-grid" aria-label="Business summary">
        <Metric label="Conversations today" value="28" change="+6 from yesterday" icon={ChatCircleDots} positive />
        <Metric label="Orders this week" value="23" change="4 awaiting payment" icon={ShoppingBagOpen} />
        <Metric label="Sales this week" value={formatCurrency(8420)} change="+12% from last week" icon={CreditCard} positive />
        <Metric label="Need your attention" value={`${needsReply + 2}`} change={`${needsReply} conversations · 2 approvals`} icon={WarningCircle} attention />
      </section>

      <section className="overview-primary-grid">
        <div className="panel activity-panel">
          <div className="panel-heading">
            <div><h2>Recent conversations</h2><p>Customer messages that may need your attention</p></div>
            <button className="text-link" onClick={() => navigate('inbox')}>Open inbox <ArrowRight size={15} /></button>
          </div>
          <div className="conversation-preview-list">
            {conversations.slice(0, 4).map((conversation) => (
              <button className="conversation-preview-row" key={conversation.id} onClick={() => openConversation(conversation.id)}>
                <Avatar initials={conversation.initials} color={conversation.color} />
                <span className="preview-conversation-main">
                  <span className="preview-name-row"><strong>{conversation.name}</strong><small>{conversation.time}</small></span>
                  <span className="preview-message">{conversation.preview}</span>
                </span>
                {conversation.status === 'Needs reply' && <span className="needs-reply-label">Needs reply</span>}
                <CaretRight className="preview-chevron" size={16} />
              </button>
            ))}
          </div>
        </div>

        <aside className="panel agent-status-panel">
          <div className="panel-heading">
            <div><h2>Your business agent</h2><p>Responding across your connected channels</p></div>
            <span className={`agent-indicator ${agentEnabled ? 'is-on' : 'is-off'}`} aria-label={agentEnabled ? 'Agent active' : 'Agent paused'} />
          </div>
          <div className="agent-status-card">
            <div className="agent-avatar"><Robot size={23} weight="duotone" /></div>
            <div><strong>{agentEnabled ? 'Agent is active' : 'Agent is paused'}</strong><span>{agentEnabled ? 'Available to respond to customers' : 'Messages will wait for your team'}</span></div>
          </div>
          <div className="agent-channel-list">
            <div><TelegramLogo size={18} /><span>Telegram</span><Badge color={connections.Telegram ? 'green' : 'gray'} variant="soft">{connections.Telegram ? 'Connected' : 'Not connected'}</Badge></div>
            <div><Storefront size={18} /><span>WooCommerce</span><Badge color={connections.WooCommerce ? 'green' : 'gray'} variant="soft">{connections.WooCommerce ? 'Synced' : 'Not connected'}</Badge></div>
          </div>
          <button className="panel-footer-link" onClick={() => navigate('agent')}>Manage agent settings <ArrowRight size={15} /></button>
        </aside>
      </section>

      <section className="overview-secondary-grid">
        <div className="panel orders-panel">
          <div className="panel-heading">
            <div><h2>Latest orders</h2><p>{paidOrders} orders paid or processing this week</p></div>
            <button className="text-link" onClick={() => navigate('orders')}>View all <ArrowRight size={15} /></button>
          </div>
          <div className="latest-orders-list">
            {orders.slice(0, 3).map((order) => (
              <button className="latest-order-row" key={order.id} onClick={() => openOrder(order.id)}>
                <span className="order-icon"><ShoppingBagOpen size={18} /></span>
                <span className="latest-order-copy"><strong>{order.customer}</strong><small>{order.id} <span>·</span> {order.item}</small></span>
                <span className="latest-order-total">{formatCurrency(order.total)}</span>
                <OrderStatus status={order.status} />
              </button>
            ))}
          </div>
        </div>
        <div className="panel setup-panel">
          <div className="panel-heading">
            <div><h2>Workspace setup</h2><p>{setupComplete ? 'Your core setup is ready' : 'Finish setting up your agent'}</p></div>
            <span className="setup-complete">{completedSetupSteps} of 3</span>
          </div>
          <div className="setup-progress-track"><span style={{ width: `${completedSetupSteps / 3 * 100}%` }} /></div>
          <div className="setup-list">
            {productSourceReady
              ? <div className="setup-item done"><CheckCircle size={18} weight="fill" /><span><strong>Product source ready</strong><small>{productSourceDescription}</small></span></div>
              : <button className="setup-item setup-next" onClick={() => navigate('catalog')}><span className="setup-step-icon"><Package size={16} /></span><span><strong>Add products or connect a store</strong><small>Build a catalog your agent can use</small></span><ArrowRight size={16} /></button>}
            {connections.Telegram
              ? <div className="setup-item done"><CheckCircle size={18} weight="fill" /><span><strong>Telegram connected</strong><small>Your agent can receive messages</small></span></div>
              : <button className="setup-item setup-next" onClick={() => navigate('integrations')}><span className="setup-step-icon"><TelegramLogo size={16} /></span><span><strong>Connect a customer channel</strong><small>Choose where your agent can respond</small></span><ArrowRight size={16} /></button>}
            {paymentConnected
              ? <div className="setup-item done"><CheckCircle size={18} weight="fill" /><span><strong>Payments connected</strong><small>PayPal is ready for checkout</small></span></div>
              : <button className="setup-item setup-next" onClick={() => setConnectionDialog('PayPal')}><span className="setup-step-icon"><CreditCard size={16} /></span><span><strong>Set up payments</strong><small>Connect PayPal to accept payments</small></span><ArrowRight size={16} /></button>}
          </div>
        </div>
      </section>
      <p className="preview-footnote"><InfoIcon /> This workspace contains sample data. Changes in this preview are not sent to customers or providers.</p>
    </div>
  )
}

function Metric({ label, value, change, icon: IconComponent, positive, attention }: { label: string; value: string; change: string; icon: Icon; positive?: boolean; attention?: boolean }) {
  return (
    <article className={`metric-card ${attention ? 'metric-attention' : ''}`}>
      <div className="metric-topline"><span>{label}</span><span className={`metric-icon ${attention ? 'metric-icon-attention' : ''}`}><IconComponent size={18} /></span></div>
      <strong className="metric-value">{value}</strong>
      <span className={`metric-change ${positive ? 'change-positive' : ''}`}>{positive && <ArrowUpRight size={13} />}{change}</span>
    </article>
  )
}

function InfoIcon() {
  return <WarningCircle size={15} />
}

function readCatalogImage(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      if (typeof reader.result === 'string') resolve(reader.result)
      else reject(new Error(`Could not read ${file.name}. Choose another image.`))
    }
    reader.onerror = () => reject(new Error(`Could not read ${file.name}. Choose another image.`))
    reader.readAsDataURL(file)
  })
}

function Catalog({
  products,
  setProducts,
  notify,
}: {
  products: CatalogProduct[]
  setProducts: React.Dispatch<React.SetStateAction<CatalogProduct[]>>
  notify: (message: string) => void
}) {
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [category, setCategory] = useState('')
  const [price, setPrice] = useState('')
  const [stock, setStock] = useState('')
  const [images, setImages] = useState<string[]>([])
  const [readingImages, setReadingImages] = useState(false)
  const [agentCanShare, setAgentCanShare] = useState(true)
  const [formError, setFormError] = useState('')
  const [search, setSearch] = useState('')
  const [visibility, setVisibility] = useState<'all' | 'shared' | 'hidden'>('all')

  function openProductForm(product?: CatalogProduct) {
    setEditingId(product?.id ?? null)
    setName(product?.name ?? '')
    setDescription(product?.description ?? '')
    setCategory(product?.category ?? '')
    setPrice(product ? String(product.price) : '')
    setStock(product?.stock === null || product?.stock === undefined ? '' : String(product.stock))
    setImages(product?.images ?? [])
    setAgentCanShare(product?.agentCanShare ?? true)
    setFormError('')
    setDialogOpen(true)
  }

  async function addImages(files: FileList | File[]) {
    const selected = Array.from(files)
    if (!selected.length || readingImages) return
    if (images.length + selected.length > 6) {
      setFormError('Add up to 6 photos per product.')
      return
    }
    const oversizedFile = selected.find((file) => file.size > 5 * 1024 * 1024)
    if (oversizedFile) {
      setFormError(`${oversizedFile.name} is over 5 MB. Choose a smaller image.`)
      return
    }
    const supportedTypes = ['image/jpeg', 'image/png', 'image/webp']
    const invalidFile = selected.find((file) => !supportedTypes.includes(file.type))
    if (invalidFile) {
      setFormError(`${invalidFile.name} is not a supported image. Choose a JPG, PNG, or WebP file.`)
      return
    }
    setReadingImages(true)
    try {
      const loadedImages = await Promise.all(selected.map(readCatalogImage))
      setImages((current) => [...current, ...loadedImages])
      setFormError('')
    } catch (error) {
      setFormError(error instanceof Error ? error.message : 'Could not load the selected images.')
    } finally {
      setReadingImages(false)
    }
  }

  function saveProduct(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (images.length === 0) {
      setFormError('Add at least one product photo.')
      return
    }
    if (!name.trim()) {
      setFormError('Enter a product name.')
      return
    }
    const parsedPrice = Number(price)
    const parsedStock = stock.trim() === '' ? null : Number(stock)
    if (!Number.isFinite(parsedPrice) || parsedPrice <= 0) {
      setFormError('Enter a price greater than zero.')
      return
    }
    if (parsedStock !== null && (!Number.isInteger(parsedStock) || parsedStock < 0)) {
      setFormError('Stock must be a whole number of zero or more.')
      return
    }
    const product: CatalogProduct = {
      id: editingId ?? `manual-${Date.now()}`,
      name: name.trim(),
      description: description.trim(),
      category: category.trim(),
      price: parsedPrice,
      stock: parsedStock,
      images,
      available: parsedStock !== 0,
      agentCanShare,
    }
    setProducts((current) => editingId
      ? current.map((item) => item.id === editingId ? product : item)
      : [product, ...current],
    )
    setDialogOpen(false)
    notify(editingId ? 'Product updated in this preview' : 'Product added to this preview catalog')
  }

  function toggleAgentAccess(productId: string) {
    setProducts((current) => current.map((product) =>
      product.id === productId ? { ...product, agentCanShare: !product.agentCanShare } : product,
    ))
  }

  function removeProduct(product: CatalogProduct) {
    setProducts((current) => current.filter((item) => item.id !== product.id))
    notify(`${product.name} removed from this preview catalog`)
  }

  const visibleProducts = products.filter((product) => {
    const matchesSearch = `${product.name} ${product.category} ${product.description}`.toLowerCase().includes(search.toLowerCase())
    const matchesVisibility = visibility === 'all'
      || (visibility === 'shared' && product.agentCanShare)
      || (visibility === 'hidden' && !product.agentCanShare)
    return matchesSearch && matchesVisibility
  })

  return (
    <div className="page-body catalog-page">
      <PageHeading
        title="Catalog"
        description="Add products and photos for your agent to use in customer conversations. This is not an online store."
        action={<Button onClick={() => openProductForm()}><Plus size={17} /> Add product</Button>}
      />

      <section className="catalog-intro panel">
        <div className="catalog-intro-icon"><ImageSquare size={23} /></div>
        <div className="catalog-intro-copy">
          <h2>Sell through chat? Start here.</h2>
          <p>Upload the products you share on WhatsApp, Instagram, or in messages. Add prices and useful details once, then let your agent find the right product and share its photos with customers.</p>
        </div>
        <div className="catalog-intro-note"><Robot size={16} /><span>Only products you share with the agent are available to it.</span></div>
      </section>

      <div className="catalog-toolbar">
        <div className="catalog-count"><strong>{products.length}</strong><span>{products.length === 1 ? 'product' : 'products'}</span></div>
        <div className="catalog-filters">
          <label className="catalog-search">
            <MagnifyingGlass size={17} />
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search products" aria-label="Search catalog products" />
          </label>
          <select className="catalog-filter-select" value={visibility} onChange={(event) => setVisibility(event.target.value as typeof visibility)} aria-label="Filter by agent access">
            <option value="all">All products</option>
            <option value="shared">Available to agent</option>
            <option value="hidden">Hidden from agent</option>
          </select>
        </div>
      </div>

      {products.length === 0 ? (
        <section className="catalog-empty panel">
          <span className="catalog-empty-icon"><UploadSimple size={23} /></span>
          <h2>Add your first product</h2>
          <p>Upload clear photos, add the price and details, and choose whether your agent can recommend and share it.</p>
          <Button onClick={() => openProductForm()}><Plus size={16} /> Add a product</Button>
          <small>You do not need a website or online store to use the catalog.</small>
        </section>
      ) : visibleProducts.length === 0 ? (
        <section className="catalog-empty panel">
          <span className="catalog-empty-icon"><MagnifyingGlass size={22} /></span>
          <h2>No matching products</h2>
          <p>Try a different search or agent access filter.</p>
          <Button variant="soft" color="gray" onClick={() => { setSearch(''); setVisibility('all') }}>Clear filters</Button>
        </section>
      ) : (
        <div className="catalog-grid">
          {visibleProducts.map((product) => (
            <article className={`catalog-product panel ${!product.available ? 'catalog-product-unavailable' : ''}`} key={product.id}>
              <div className="catalog-product-image-wrap">
                <img src={product.images[0]} alt={product.name} />
                {product.images.length > 1 && <span className="catalog-image-count"><ImageSquare size={13} /> {product.images.length} photos</span>}
                {!product.available && <span className="catalog-product-state">Out of stock</span>}
              </div>
              <div className="catalog-product-details">
                <div className="catalog-product-title-row">
                  <div>
                    <h2>{product.name}</h2>
                    <div className="catalog-product-labels">
                      <span className="catalog-source-tag">Added in Reactant</span>
                      {product.category && <span className="catalog-category">{product.category}</span>}
                    </div>
                  </div>
                  <strong className="catalog-price">{formatCurrency(product.price)}</strong>
                </div>
                {product.description && <p className="catalog-product-description">{product.description}</p>}
                <div className="catalog-product-meta">
                  <span>{product.stock === null ? 'Stock not tracked' : `${product.stock} in stock`}</span>
                  <button
                    className={`catalog-agent-access ${product.agentCanShare ? 'catalog-agent-enabled' : ''}`}
                    onClick={() => toggleAgentAccess(product.id)}
                    aria-pressed={product.agentCanShare}
                  >
                    <Robot size={14} /> {product.agentCanShare ? 'Agent can share' : 'Hidden from agent'}
                  </button>
                </div>
                <div className="catalog-product-actions">
                  <Button variant="soft" color="gray" onClick={() => openProductForm(product)}>Edit product</Button>
                  <button className="catalog-remove-button" onClick={() => removeProduct(product)} aria-label={`Remove ${product.name}`}><Trash size={16} /></button>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}

      <Dialog.Root open={dialogOpen} onOpenChange={setDialogOpen}>
        <Dialog.Content className="dialog-content catalog-dialog-content">
          <Dialog.Title className="dialog-title">{editingId ? 'Edit product' : 'Add a product'}</Dialog.Title>
          <Dialog.Description className="dialog-description">Add the details your agent needs to answer questions and share the right product photos.</Dialog.Description>
          <form className="catalog-product-form" onSubmit={saveProduct}>
            <label className="field-label" htmlFor="catalog-name">Product name</label>
            <TextField.Root id="catalog-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="For example, handwoven market basket" required />

            <div className="catalog-form-row">
              <div>
                <label className="field-label" htmlFor="catalog-price">Price (USD)</label>
                <TextField.Root id="catalog-price" type="number" min="0.01" step="0.01" value={price} onChange={(event) => setPrice(event.target.value)} placeholder="0.00" required />
              </div>
              <div>
                <label className="field-label" htmlFor="catalog-category">Category</label>
                <TextField.Root id="catalog-category" value={category} onChange={(event) => setCategory(event.target.value)} placeholder="Clothing, food, home..." />
              </div>
            </div>

            <label className="field-label" htmlFor="catalog-description">Product details</label>
            <textarea id="catalog-description" className="catalog-description-input" rows={3} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Materials, sizes, colours, or anything customers often ask." />

            <label className="field-label" htmlFor="catalog-stock">Stock on hand <span className="catalog-optional-label">Optional</span></label>
            <TextField.Root id="catalog-stock" type="number" min="0" step="1" value={stock} onChange={(event) => setStock(event.target.value)} placeholder="Leave blank if you do not track stock" />
            <small className="catalog-field-help">If stock is not tracked, your agent will not make availability promises.</small>

            <div className="catalog-upload-block">
              <span className="field-label">Product photos <span className="catalog-optional-label">Up to 6, 5 MiB each</span></span>
              <label
                className="catalog-upload-dropzone"
                htmlFor="catalog-images"
                aria-disabled={readingImages}
                onDragOver={(event) => event.preventDefault()}
                onDrop={(event) => { event.preventDefault(); void addImages(event.dataTransfer.files) }}
              >
                <UploadSimple size={19} />
                <span><strong>{readingImages ? 'Preparing photos...' : 'Choose photos'}</strong>{!readingImages && ' or drag them here'}</span>
                <small>JPG, PNG, or WebP</small>
              </label>
              <input id="catalog-images" className="sr-only" type="file" accept="image/jpeg,image/png,image/webp" multiple disabled={readingImages} onChange={(event) => { void addImages(event.currentTarget.files ?? []); event.currentTarget.value = '' }} />
              {images.length > 0 && (
                <div className="catalog-image-previews">
                  {images.map((image, index) => (
                    <div className="catalog-image-preview" key={`${image.slice(0, 40)}-${index}`}>
                      <img src={image} alt={`Product photo ${index + 1}`} />
                      <button type="button" onClick={() => setImages((current) => current.filter((_, imageIndex) => imageIndex !== index))} aria-label={`Remove product photo ${index + 1}`}><X size={14} /></button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <label className="catalog-agent-toggle">
              <input type="checkbox" checked={agentCanShare} onChange={(event) => setAgentCanShare(event.target.checked)} />
              <span><strong>Make available to my agent</strong><small>The agent can use these details and share product photos with customers.</small></span>
            </label>

            {formError && <p className="catalog-form-error" role="alert">{formError}</p>}
            <p className="form-note">Preview only. This product is not yet saved to Reactant or connected to customer channels.</p>
            <div className="dialog-actions">
              <Button type="button" variant="soft" color="gray" onClick={() => setDialogOpen(false)}>Cancel</Button>
              <Button type="submit">{editingId ? 'Save changes' : 'Add to catalog'}</Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Root>
    </div>
  )
}

function Inbox({
  conversations,
  selectedConversation,
  filter,
  setFilter,
  setSearch,
  search,
  setSelected,
  sendReply,
  reply,
  setReply,
  setStatus,
}: {
  conversations: Conversation[]
  selectedConversation: Conversation
  filter: 'All' | ConversationStatus
  setFilter: (filter: 'All' | ConversationStatus) => void
  setSearch: (value: string) => void
  search: string
  setSelected: (id: string) => void
  sendReply: (event: React.FormEvent<HTMLFormElement>) => void
  reply: string
  setReply: (value: string) => void
  setStatus: (id: string, status: ConversationStatus) => void
}) {
  return (
    <div className="page-body inbox-page">
      <PageHeading title="Inbox" description="Keep every customer conversation moving." meta={<Badge className="preview-data-label" color="gray" variant="soft" radius="full">Sample data</Badge>} />
      <div className="inbox-layout">
        <section className="panel inbox-list-panel" aria-label="Conversations">
          <div className="inbox-list-toolbar">
            <TextField.Root placeholder="Search conversations" value={search} onChange={(event) => setSearch(event.target.value)} aria-label="Search conversations">
              <TextField.Slot><MagnifyingGlass size={16} /></TextField.Slot>
            </TextField.Root>
            <Button variant="soft" color="gray" aria-label={filter === 'All' ? 'Show conversations needing a reply' : 'Show all conversations'} onClick={() => setFilter(filter === 'All' ? 'Needs reply' : 'All')}><Funnel size={16} /></Button>
          </div>
          <div className="inbox-filters" role="tablist" aria-label="Filter conversations">
            {(['All', 'Needs reply', 'Open', 'Resolved'] as const).map((item) => (
              <button key={item} className={`inbox-filter ${filter === item ? 'inbox-filter-active' : ''}`} onClick={() => setFilter(item)} role="tab" aria-selected={filter === item}>{item}</button>
            ))}
          </div>
          <div className="inbox-conversation-list">
            {conversations.length === 0 && <div className="empty-list">No conversations match this filter.</div>}
            {conversations.map((conversation) => (
              <button className={`inbox-conversation ${selectedConversation.id === conversation.id ? 'inbox-conversation-selected' : ''}`} key={conversation.id} onClick={() => setSelected(conversation.id)}>
                <Avatar initials={conversation.initials} color={conversation.color} />
                <span className="inbox-conversation-info">
                  <span className="inbox-conversation-name"><strong>{conversation.name}</strong><small>{conversation.time}</small></span>
                  <span className="inbox-conversation-preview">{conversation.preview}</span>
                  <span className="inbox-conversation-tags"><span className="channel-tag"><TelegramLogo size={12} /> Telegram</span>{conversation.status === 'Needs reply' && <span className="needs-reply-label">Needs reply</span>}</span>
                </span>
                {conversation.unread && <span className="unread-indicator" aria-label="Unread" />}
              </button>
            ))}
          </div>
        </section>

        <section className="panel conversation-panel" aria-label={`Conversation with ${selectedConversation.name}`}>
          <div className="conversation-header">
            <div className="conversation-person">
              <Avatar initials={selectedConversation.initials} color={selectedConversation.color} />
              <div><strong>{selectedConversation.name}</strong><span><TelegramLogo size={13} /> Telegram · {selectedConversation.id}</span></div>
            </div>
            <div className="conversation-header-actions">
              <Badge color={selectedConversation.status === 'Needs reply' ? 'orange' : selectedConversation.status === 'Resolved' ? 'gray' : 'green'} variant="soft">{selectedConversation.status}</Badge>
            </div>
          </div>
          <div className="conversation-context">
            <span><ShoppingBagOpen size={15} /> 1 related order</span>
            <button onClick={() => setStatus(selectedConversation.id, selectedConversation.status === 'Resolved' ? 'Open' : 'Resolved')}>
              {selectedConversation.status === 'Resolved' ? <ArrowLeft size={14} /> : <Check size={14} />}
              {selectedConversation.status === 'Resolved' ? 'Reopen' : 'Resolve'}
            </button>
          </div>
          <div className="message-thread">
            <p className="thread-date">Today</p>
            {selectedConversation.messages.map((message, index) => (
              <div className={`message-row message-${message.from}`} key={`${selectedConversation.id}-${index}`}>
                {message.from === 'customer' && <Avatar initials={selectedConversation.initials} color={selectedConversation.color} small />}
                <div className="message-content">
                  {message.from !== 'customer' && <span className="message-sender">{message.from === 'agent' ? 'Reactant agent' : 'You'}</span>}
                  <div className="message-bubble">{message.text}</div>
                  <span className="message-time">{message.time}</span>
                </div>
              </div>
            ))}
          </div>
          <form className="reply-composer" onSubmit={sendReply}>
            <textarea value={reply} onChange={(event) => setReply(event.target.value)} placeholder="Write a reply..." aria-label="Write a reply" rows={2} />
            <div className="composer-footer"><span>Replying as Ada · Preview only</span><Button type="submit" disabled={!reply.trim()}><PaperPlaneTilt size={15} /> Send reply</Button></div>
          </form>
        </section>
      </div>
    </div>
  )
}

function Orders({
  orders,
  selectedOrder,
  filter,
  setFilter,
  search,
  setSearch,
  selectOrder,
  createOrder,
}: {
  orders: Order[]
  selectedOrder?: Order
  filter: string
  setFilter: (filter: string) => void
  search: string
  setSearch: (value: string) => void
  selectOrder: (id: string | null) => void
  createOrder: (customer: string, item: string, total: number) => void
}) {
  const [createOrderOpen, setCreateOrderOpen] = useState(false)

  function submitOrder(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const formData = new FormData(event.currentTarget)
    const customer = String(formData.get('customer') ?? '')
    const item = String(formData.get('item') ?? '')
    const total = Number(formData.get('total'))
    createOrder(customer, item, total)
    setCreateOrderOpen(false)
  }

  return (
    <div className="page-body orders-page">
      <PageHeading title="Orders" description="Track orders and payment status in one place." meta={<Badge className="preview-data-label" color="gray" variant="soft" radius="full">Sample data</Badge>} action={<Button onClick={() => setCreateOrderOpen(true)}><Plus size={17} /> Create order</Button>} />
      <section className="panel orders-table-panel">
        <div className="table-toolbar">
          <div className="order-tabs" role="tablist" aria-label="Filter orders">
            {['All orders', 'Pending payment', 'Processing', 'Paid'].map((item) => <button key={item} className={`order-tab ${filter === item ? 'order-tab-active' : ''}`} onClick={() => setFilter(item)} role="tab" aria-selected={filter === item}>{item}</button>)}
          </div>
          <div className="table-tools">
            <TextField.Root placeholder="Search orders" value={search} onChange={(event) => setSearch(event.target.value)} aria-label="Search orders"><TextField.Slot><MagnifyingGlass size={15} /></TextField.Slot></TextField.Root>
          </div>
        </div>
        <div className="orders-table-scroll">
          <table className="orders-table">
            <thead><tr><th>Order</th><th>Customer</th><th>Items</th><th>Date</th><th>Total</th><th>Status</th><th aria-label="Actions" /></tr></thead>
            <tbody>
              {orders.map((order) => (
                <tr key={order.id} className={selectedOrder?.id === order.id ? 'selected-order-row' : ''} onClick={() => selectOrder(order.id)}>
                  <td><button className="order-id-link" onClick={(event) => { event.stopPropagation(); selectOrder(order.id) }}>{order.id}</button></td>
                  <td><span className="table-customer"><Avatar initials={order.initials} color={colorForInitials(order.initials)} small />{order.customer}</span></td>
                  <td className="table-item-cell">{order.item}</td>
                  <td className="muted-cell">{order.date}</td>
                  <td className="total-cell">{formatCurrency(order.total)}</td>
                  <td><OrderStatus status={order.status} /></td>
                  <td><button className="icon-button row-more" aria-label={`More actions for ${order.id}`} onClick={(event) => { event.stopPropagation(); selectOrder(order.id) }}><DotsThree size={20} /></button></td>
                </tr>
              ))}
              {orders.length === 0 && <tr><td className="table-empty-cell" colSpan={7}>No orders found. Try another filter or search.</td></tr>}
            </tbody>
          </table>
        </div>
        <div className="table-pagination"><span>Showing {orders.length} sample orders</span><div><Button size="1" variant="soft" color="gray" disabled><ArrowLeft size={14} /> Previous</Button><Button size="1" variant="soft" color="gray" disabled>Next <ArrowRight size={14} /></Button></div></div>
      </section>
      <Dialog.Root open={createOrderOpen} onOpenChange={setCreateOrderOpen}>
        <Dialog.Content className="dialog-content">
          <Dialog.Title className="dialog-title">Create a sample order</Dialog.Title>
          <Dialog.Description className="dialog-description">Add an order to the local preview. It will not be sent to a store or payment provider.</Dialog.Description>
          <form className="connection-form" onSubmit={submitOrder}>
            <label className="field-label" htmlFor="order-customer">Customer name</label>
            <TextField.Root id="order-customer" name="customer" placeholder="Customer name" required />
            <label className="field-label" htmlFor="order-item">Product or item</label>
            <TextField.Root id="order-item" name="item" placeholder="Product name" required />
            <label className="field-label" htmlFor="order-total">Order total (USD)</label>
            <TextField.Root id="order-total" name="total" type="number" min="1" step="0.01" placeholder="0.00" required />
            <div className="dialog-actions">
              <Button type="button" variant="soft" color="gray" onClick={() => setCreateOrderOpen(false)}>Cancel</Button>
              <Button type="submit">Create sample order</Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Root>
      {selectedOrder && (
        <div className="order-detail-backdrop" onClick={() => selectOrder(null)}>
          <aside className="order-detail-drawer" onClick={(event) => event.stopPropagation()} aria-label={`Order details for ${selectedOrder.id}`}>
            <div className="drawer-heading"><div><span className="drawer-eyebrow">Order details</span><h2>{selectedOrder.id}</h2></div><button className="icon-button" aria-label="Close order details" onClick={() => selectOrder(null)}><X size={19} /></button></div>
            <OrderStatus status={selectedOrder.status} />
            <div className="detail-section"><h3>Customer</h3><div className="detail-customer"><Avatar initials={selectedOrder.initials} color={colorForInitials(selectedOrder.initials)} /><span><strong>{selectedOrder.customer}</strong><small>{selectedOrder.email}</small></span></div></div>
            <div className="detail-section"><h3>Items</h3><div className="detail-item"><span className="order-icon"><ShoppingBagOpen size={18} /></span><span><strong>{selectedOrder.item}</strong><small>Quantity 1</small></span><strong>{formatCurrency(selectedOrder.total)}</strong></div></div>
            <div className="detail-section"><h3>Payment summary</h3><div className="summary-row"><span>Subtotal</span><strong>{formatCurrency(selectedOrder.total)}</strong></div><div className="summary-row"><span>Delivery</span><strong>Calculated at checkout</strong></div><div className="summary-row summary-total"><span>Total</span><strong>{formatCurrency(selectedOrder.total)}</strong></div></div>
            <div className="detail-section"><h3>Timeline</h3><div className="order-timeline"><span className="timeline-icon"><CheckCircle size={16} /></span><span><strong>Order created</strong><small>{selectedOrder.date}</small></span></div></div>
            <Button variant="soft" color="gray" className="drawer-action" onClick={() => selectOrder(null)}>Close details</Button>
          </aside>
        </div>
      )}
    </div>
  )
}

function Approvals({ orders, decide, resolveHandoff, pendingCount }: { orders: Order[]; decide: (id: string, decision: 'approve' | 'reject') => void; resolveHandoff: () => void; pendingCount: number }) {
  const pendingOrder = orders.find((order) => order.status === 'Pending payment')
  const [resolvedRequests, setResolvedRequests] = useState<string[]>([])

  function resolveRequest(request: string) {
    setResolvedRequests((items) => [...items, request])
  }

  return (
    <div className="page-body approvals-page">
      <PageHeading title="Approvals" description="Review sensitive actions before your agent proceeds." meta={<Badge className="preview-data-label" color="gray" variant="soft" radius="full">Sample data</Badge>} />
      <div className="approvals-summary">
        <div className="approval-summary-icon"><ShieldCheck size={20} /></div>
        <div><strong>{pendingCount === 0 ? 'You’re all caught up' : `${pendingCount} ${pendingCount === 1 ? 'action needs' : 'actions need'} your review`}</strong><p>Orders and other sensitive actions wait here when approval is required.</p></div>
      </div>
      {pendingCount > 0 && (
        <div className={`approval-list ${pendingCount === 1 ? 'approval-list-single' : ''}`}>
          {!resolvedRequests.includes('order') && (
          <ApprovalCard
            title="Approve order creation"
            subtitle="The agent prepared an order after a customer confirmed their cart."
            customer="Ama Mensah"
            initials="AM"
            amount={formatCurrency(620)}
            time="Requested 12 minutes ago"
            onApprove={() => { if (pendingOrder) decide(pendingOrder.id, 'approve'); resolveRequest('order') }}
            onReject={() => { if (pendingOrder) decide(pendingOrder.id, 'reject'); resolveRequest('order') }}
          />
          )}
          {!resolvedRequests.includes('handoff') && (
          <ApprovalCard
            title="Confirm a customer handoff"
            subtitle="A delivery question needs a staff member to verify the latest tracking details."
            customer="Esi Owusu"
            initials="EO"
            amount="Conversation C-2046"
            time="Requested 42 minutes ago"
            onApprove={() => { resolveHandoff(); resolveRequest('handoff') }}
            onReject={() => { resolveHandoff(); resolveRequest('handoff') }}
          />
          )}
        </div>
      )}
      {pendingCount === 0 && <div className="empty-state"><span className="empty-state-icon"><CheckCircle size={25} /></span><h2>No pending approvals</h2><p>New requests will appear here when an action needs your review.</p></div>}
      <p className="preview-footnote"><WarningCircle size={15} /> Approval decisions here only update sample data in this preview.</p>
    </div>
  )
}

function ApprovalCard({ title, subtitle, customer, initials, amount, time, onApprove, onReject }: { title: string; subtitle: string; customer: string; initials: string; amount: string; time: string; onApprove: () => void; onReject: () => void }) {
  return (
    <article className="panel approval-card">
      <div className="approval-card-top"><span className="approval-action-icon"><Clock size={18} /></span><span className="approval-request-time">{time}</span></div>
      <h2>{title}</h2>
      <p>{subtitle}</p>
      <div className="approval-requester"><Avatar initials={initials} color={colorForInitials(initials)} /><span><strong>{customer}</strong><small>{amount}</small></span></div>
      <div className="approval-actions"><Button variant="soft" color="gray" onClick={onReject}>Decline</Button><Button onClick={onApprove}><Check size={16} /> Approve</Button></div>
    </article>
  )
}

function Integrations({ connections, setConnectionDialog }: { connections: Record<Connection, boolean>; setConnectionDialog: (connection: Connection) => void }) {
  const integrations: { name: Connection; description: string; icon: Icon; category: string }[] = [
    { name: 'WooCommerce', description: 'Sync your products, stock, and orders from your online store.', icon: Storefront, category: 'Store' },
    { name: 'Telegram', description: 'Talk to customers through your business Telegram bot.', icon: TelegramLogo, category: 'Messaging' },
    { name: 'PayPal', description: 'Offer secure customer checkout and verify payments.', icon: CreditCard, category: 'Payments' },
    { name: 'Shopify', description: 'Bring your products and order activity into Reactant.', icon: ShoppingBagOpen, category: 'Store' },
    { name: 'WhatsApp', description: 'Meet customers on the messaging app they already use.', icon: ChatCircleDots, category: 'Messaging' },
  ]
  return (
    <div className="page-body integrations-page">
      <PageHeading title="Integrations" description="Connect the tools your business already uses." meta={<Badge className="preview-data-label" color="gray" variant="soft" radius="full">Sample data</Badge>} action={<Button onClick={() => setConnectionDialog('WooCommerce')}><Plus size={17} /> Add integration</Button>} />
      <div className="integration-callout"><span className="callout-icon"><ShieldCheck size={20} /></span><span><strong>Your accounts stay yours.</strong><small>Connections use limited access, and you can disconnect them at any time.</small></span></div>
      <div className="integration-grid">
        {integrations.map((item) => {
          const IconComponent = item.icon
          const connected = connections[item.name]
          return (
            <article className={`panel integration-card ${connected ? 'integration-connected' : ''}`} key={item.name}>
              <div className="integration-card-top"><span className={`integration-icon integration-icon-${item.name.toLowerCase()}`}><IconComponent size={22} /></span><Badge color="gray" variant="soft">{item.category}</Badge></div>
              <h2>{item.name}</h2>
              <p>{item.description}</p>
              {connected && <div className="integration-status"><CheckCircle size={15} weight="fill" /><span>Connected</span>{item.name === 'WooCommerce' && <small>Last synced today</small>}</div>}
              <div className="integration-card-actions">
                {connected ? <Button variant="soft" color="gray" onClick={() => setConnectionDialog(item.name)}>Manage</Button> : <Button onClick={() => setConnectionDialog(item.name)}>Connect</Button>}
              </div>
            </article>
          )
        })}
      </div>
      <p className="preview-footnote"><WarningCircle size={15} /> Connecting here changes preview state only. It will not authorize an external account.</p>
    </div>
  )
}

function AgentSettings({ enabled, setEnabled, notify, paymentConnected }: { enabled: boolean; setEnabled: (enabled: boolean) => void; notify: (message: string) => void; paymentConnected: boolean }) {
  const [productAnswers, setProductAnswers] = useState(true)
  const [approvalRequired, setApprovalRequired] = useState(true)
  const [productImages, setProductImages] = useState(true)
  const [cartOrders, setCartOrders] = useState(true)
  const [checkoutEnabled, setCheckoutEnabled] = useState(false)
  const [approvalThreshold, setApprovalThreshold] = useState('')
  return (
    <div className="page-body agent-page">
      <PageHeading title="Business agent" description="Set how your agent speaks and what it can do." meta={<Badge className="preview-data-label" color="gray" variant="soft" radius="full">Sample data</Badge>} action={<Button variant="soft" color="gray" onClick={() => notify('Settings saved in this preview')}><Check size={16} /> Save changes</Button>} />
      <div className="agent-page-layout">
        <div className="agent-settings-column">
          <section className="panel agent-control-panel">
            <div className="agent-control-heading"><div className="agent-avatar"><Robot size={23} weight="duotone" /></div><div><h2>Customer support agent</h2><p>Shared across your connected channels</p></div><div className="agent-toggle"><span>{enabled ? 'Active' : 'Paused'}</span><Switch checked={enabled} onCheckedChange={setEnabled} aria-label="Enable business agent" /></div></div>
            <div className={`agent-state-note ${enabled ? '' : 'agent-paused-note'}`}><span className="agent-indicator is-on" /><span>{enabled ? 'Your agent can respond to customer messages.' : 'Your agent is paused. New messages will wait in the inbox.'}</span></div>
          </section>
          <section className="panel settings-section">
            <div className="settings-section-heading"><h2>Business profile</h2><p>Give the agent the context it needs to represent your business.</p></div>
            <label className="field-label" htmlFor="business-description">About your business</label>
            <textarea id="business-description" className="settings-textarea" defaultValue="Olive & Oak Studio makes thoughtfully sourced home goods, ceramics, and textiles. We are based in Accra and ship across Ghana." rows={3} />
            <div className="settings-two-column">
              <div><label className="field-label" htmlFor="agent-tone">Tone of voice</label><select className="settings-select" id="agent-tone" defaultValue="Warm and helpful"><option>Warm and helpful</option><option>Direct and concise</option><option>Professional</option></select></div>
              <div><label className="field-label" htmlFor="handoff-rule">Human handoff</label><select className="settings-select" id="handoff-rule" defaultValue="When the agent is unsure"><option>When the agent is unsure</option><option>When a customer asks</option><option>Always offer a person</option></select></div>
            </div>
          </section>
          <section className="panel settings-section">
            <div className="settings-section-heading"><h2>What your agent can do</h2><p>Business actions are checked against your policies before they run.</p></div>
            <div className="permission-list">
              <PermissionRow title="Answer product questions" description="Use store-synced or manually added catalog details." checked={productAnswers} onChange={setProductAnswers} />
              <PermissionRow title="Share product images" description="Send photos from your catalog or connected store." enabled checked={productImages} onChange={setProductImages} />
              <PermissionRow title="Build carts and prepare orders" description="Validate product, quantity, and price before checkout." checked={cartOrders} onChange={setCartOrders} />
              <PermissionRow title="Create PayPal checkout links" description={paymentConnected ? 'Create a customer checkout link for a verified order. This never sends money from your account.' : 'Connect PayPal before enabling customer checkout links.'} checked={checkoutEnabled} onChange={paymentConnected ? setCheckoutEnabled : undefined} disabled={!paymentConnected} />
              <PermissionRow title="Require approval for sensitive actions" description="Review order actions before the agent proceeds." checked={approvalRequired} onChange={setApprovalRequired} />
            </div>
            {approvalRequired && (
              <div className="approval-threshold">
                <label className="field-label" htmlFor="checkout-threshold">Require approval for checkout amounts above</label>
                <div className="threshold-input-row"><span>$</span><input id="checkout-threshold" type="number" min="0" value={approvalThreshold} onChange={(event) => setApprovalThreshold(event.target.value)} placeholder="Every checkout" aria-describedby="checkout-threshold-help" /></div>
                <small id="checkout-threshold-help">Leave blank to require approval for every checkout. Order totals are revalidated before a link is created.</small>
              </div>
            )}
          </section>
        </div>
        <aside className="agent-settings-aside">
          <section className="panel agent-summary-panel">
            <h2>Connected channels</h2>
            <div className="connected-channel-row"><TelegramLogo size={18} /><span>Telegram</span><Badge color="green" variant="soft">Ready</Badge></div>
            <div className="connected-channel-row"><Storefront size={18} /><span>WooCommerce</span><Badge color="green" variant="soft">Ready</Badge></div>
            <div className="connected-channel-row"><CreditCard size={18} /><span>PayPal</span><Badge color={paymentConnected ? 'green' : 'gray'} variant="soft">{paymentConnected ? 'Ready' : 'Not connected'}</Badge></div>
            <button className="panel-footer-link" onClick={() => notify('Channel management is available in Integrations')}>Manage connections <ArrowRight size={15} /></button>
          </section>
          <section className="panel agent-guidelines-panel">
            <span className="guideline-icon"><ShieldCheck size={19} /></span><h2>Built to be careful</h2><p>Your agent uses verified business data and asks for help when it cannot confirm an answer.</p>
            <button className="text-link" onClick={() => notify('Safety guidelines opened in this preview')}>View safety guidelines <ArrowUpRight size={14} /></button>
          </section>
        </aside>
      </div>
      <p className="preview-footnote"><WarningCircle size={15} /> Agent settings are saved for this preview only.</p>
    </div>
  )
}

type OwnerAssistantMessage = {
  id: string
  from: 'agent' | 'owner'
  text: string
  time: string
  approval?: {
    orderId: string
    amount: string
    status: 'pending' | 'approved' | 'declined'
  }
}

const initialOwnerAssistantMessages: OwnerAssistantMessage[] = [
  {
    id: 'owner-msg-1',
    from: 'agent',
    text: 'I can answer product questions and prepare orders from your synced store data. I will check with you when a request needs a decision.',
    time: '10:14 AM',
  },
  {
    id: 'owner-msg-2',
    from: 'owner',
    text: 'Please ask me before promising same-day delivery. Our cutoff can change.',
    time: '10:17 AM',
  },
  {
    id: 'owner-msg-3',
    from: 'agent',
    text: 'Understood. A customer is ready to order the Ceramic Pour-over Set. Stock and price are verified. May I prepare a PayPal checkout link?',
    time: '10:22 AM',
    approval: { orderId: 'RA-2085', amount: formatCurrency(620), status: 'pending' },
  },
]

function OwnerAssistant({ notify, resolveApproval }: { notify: (message: string) => void; resolveApproval: () => void }) {
  const [messages, setMessages] = useState(initialOwnerAssistantMessages)
  const [draft, setDraft] = useState('')

  function sendOwnerMessage(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const text = draft.trim()
    if (!text) return
    setMessages((items) => [...items, {
      id: `owner-msg-${Date.now()}`,
      from: 'owner',
      text,
      time: 'Just now',
    }])
    setDraft('')
    notify('Message added to this preview. It was not sent to an agent service.')
  }

  function decideOwnerApproval(messageId: string, decision: 'approved' | 'declined') {
    setMessages((items) => items.map((message) =>
      message.id === messageId && message.approval
        ? { ...message, approval: { ...message.approval, status: decision } }
        : message,
    ))
    resolveApproval()
    notify(decision === 'approved'
      ? 'Checkout approval recorded in this preview. No payment link was created.'
      : 'Checkout request declined in this preview.')
  }

  return (
    <div className="page-body owner-assistant-page">
      <PageHeading
        title="Agent messages"
        description="A private conversation with your business agent, separate from customer chats."
        meta={<Badge className="preview-data-label" color="gray" variant="soft" radius="full">Private owner channel</Badge>}
      />
      <div className="owner-channel-notice">
        <span className="owner-channel-notice-icon"><ShieldCheck size={19} /></span>
        <div><strong>Only your workspace team can see this conversation.</strong><p>Customers will never receive messages from this channel. Use it to answer agent questions, review requests, and adjust how it handles your business.</p></div>
      </div>
      <section className="owner-thread panel" aria-label="Private agent conversation">
        <header className="owner-thread-header">
          <div className="owner-agent-identity">
            <span className="owner-agent-avatar"><Robot size={20} weight="duotone" /></span>
            <span><strong>Reactant business agent</strong><small>Private to Olive & Oak Studio</small></span>
          </div>
          <Badge color="green" variant="soft">Ready</Badge>
        </header>
        <div className="owner-thread-context">
          <ChatCircleDots size={17} />
          <span>This is the owner channel. Customer conversations remain in the Inbox.</span>
        </div>
        <div className="owner-message-list" aria-live="polite">
          {messages.map((message) => (
            <article key={message.id} className={`owner-message owner-message-${message.from}`}>
              <span className="owner-message-author">{message.from === 'agent' ? 'Business agent' : 'You'} <time>{message.time}</time></span>
              <p>{message.text}</p>
              {message.approval && (
                <div className="owner-approval-request">
                  <div className="owner-approval-summary">
                    <span className="owner-approval-icon"><CreditCard size={17} /></span>
                    <span><strong>PayPal checkout request</strong><small>Order {message.approval.orderId} · {message.approval.amount}</small></span>
                    <Badge color={message.approval.status === 'pending' ? 'orange' : message.approval.status === 'approved' ? 'green' : 'gray'} variant="soft">
                      {message.approval.status === 'pending' ? 'Needs review' : message.approval.status === 'approved' ? 'Approved in preview' : 'Declined'}
                    </Badge>
                  </div>
                  {message.approval.status === 'pending'
                    ? <div className="owner-approval-actions">
                        <Button variant="soft" color="gray" onClick={() => decideOwnerApproval(message.id, 'declined')}>Decline</Button>
                        <Button onClick={() => decideOwnerApproval(message.id, 'approved')}><Check size={15} /> Approve request</Button>
                      </div>
                    : <small className="owner-approval-result">Preview only. No checkout link was created.</small>}
                </div>
              )}
            </article>
          ))}
        </div>
        <form className="owner-message-composer" onSubmit={sendOwnerMessage}>
          <label className="sr-only" htmlFor="owner-agent-message">Message your business agent</label>
          <textarea id="owner-agent-message" rows={2} value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="Message your business agent..." />
          <div className="owner-composer-footer">
            <small>Preview only. Messages are not delivered to an agent service.</small>
            <Button type="submit" disabled={!draft.trim()}><PaperPlaneTilt size={16} /> Send message</Button>
          </div>
        </form>
      </section>
    </div>
  )
}

function PermissionRow({ title, description, enabled, checked, onChange, disabled }: { title: string; description: string; enabled?: boolean; checked?: boolean; onChange?: (checked: boolean) => void; disabled?: boolean }) {
  return (
    <div className="permission-row">
      <div><strong>{title}</strong><small>{description}</small></div>
      <Switch checked={enabled ? (checked ?? true) : checked} onCheckedChange={onChange} disabled={disabled} aria-label={title} />
    </div>
  )
}

function Avatar({ initials, color, small }: { initials: string; color: string; small?: boolean }) {
  return <span className={`avatar avatar-${color} ${small ? 'avatar-small' : ''}`}>{initials}</span>
}

function colorForInitials(initials: string) {
  const colorMap: Record<string, string> = { AM: 'coral', KB: 'blue', EO: 'violet', NA: 'green', KA: 'gold', AK: 'gold' }
  return colorMap[initials] ?? 'blue'
}

function OrderStatus({ status }: { status: Order['status'] }) {
  const color = status === 'Paid' ? 'green' : status === 'Processing' ? 'blue' : status === 'Pending payment' ? 'orange' : 'gray'
  return <Badge className="order-status" color={color} variant="soft" radius="full">{status}</Badge>
}

export default App
