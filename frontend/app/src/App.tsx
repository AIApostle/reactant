import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
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
import {
  apiRequest,
  apiRequestWithHeaders,
  businessPath,
  newIdempotencyKey,
  type AgentConfig,
  type Approval,
  type Business,
  type Integration,
  type OwnerMessage,
  type TelegramSetup,
} from './api'
import { getSupabaseClient, isSupabaseConfigured } from './supabase'

type Page = 'overview' | 'inbox' | 'catalog' | 'orders' | 'approvals' | 'integrations' | 'agent' | 'owner-assistant' | 'settings'
type Connection = 'WooCommerce' | 'Shopify' | 'Telegram' | 'PayPal'
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
  currency: string
  status: 'Paid' | 'Pending payment' | 'Processing' | 'Cancelled'
  email: string
}

type CatalogProduct = {
  id: string
  name: string
  description: string
  category: string
  price: number
  currency: string
  stock: number | null
  images: string[]
  imageAssetIds: string[]
  available: boolean
  agentCanShare: boolean
}

type ConversationApi = {
  id: string
  channel: string
  status: string
  customer_name: string
  last_message: { text: string; created_at: string } | null
  unread: boolean
  updated_at: string
}

type OrderApi = {
  id: string
  customer_name: string
  customer_email: string | null
  status: string
  payment_status: string
  amount_minor: number
  currency: string
  items: { product_name: string; quantity: number }[]
  created_at: string
}

type DashboardSummaryApi = {
  metrics: {
    conversations?: number
    orders?: number
    pending_approvals?: number
  }
  agent_status: string
}

type ProductApi = {
  id: string
  name: string
  description: string | null
  category: string | null
  price_minor: number
  currency: string
  stock_quantity: number | null
  status: string
  agent_enabled: boolean
  image_asset_ids: string[]
  image_urls?: string[]
}

function mapCatalogProduct(product: ProductApi, fallbackImages: string[] = []): CatalogProduct {
  const images = product.image_urls?.length ? product.image_urls : fallbackImages
  return {
    id: product.id,
    name: product.name,
    description: product.description ?? '',
    category: product.category ?? '',
    price: product.price_minor / 100,
    currency: product.currency,
    stock: product.stock_quantity,
    images,
    imageAssetIds: product.image_asset_ids,
    available: product.status === 'active' && product.stock_quantity !== 0,
    agentCanShare: product.agent_enabled,
  }
}

function displayTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

function createWebhookSecret() {
  const bytes = crypto.getRandomValues(new Uint8Array(32))
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
}

function nameInitials(name: string) {
  return name.trim().split(/\s+/).slice(0, 2).map((part) => part[0] ?? '').join('').toUpperCase() || 'CU'
}

function mapConversation(item: ConversationApi): Conversation {
  const status: ConversationStatus = item.status === 'resolved' ? 'Resolved' : item.status === 'needs_reply' ? 'Needs reply' : 'Open'
  return {
    id: item.id,
    name: item.customer_name,
    initials: nameInitials(item.customer_name),
    color: colorForInitials(nameInitials(item.customer_name)),
    channel: item.channel,
    preview: item.last_message?.text ?? 'No messages yet',
    time: displayTime(item.last_message?.created_at ?? item.updated_at),
    status,
    unread: item.unread,
    messages: [],
  }
}

function mapOrder(item: OrderApi): Order {
  const name = item.customer_name
  const status: Order['status'] = item.status === 'cancelled'
    ? 'Cancelled'
    : item.payment_status === 'paid'
      ? 'Paid'
      : item.status === 'processing' || item.status === 'completed'
        ? 'Processing'
        : 'Pending payment'
  return {
    id: item.id,
    customer: name,
    initials: nameInitials(name),
    item: item.items.map((line) => `${line.product_name}${line.quantity > 1 ? ` × ${line.quantity}` : ''}`).join(', '),
    date: displayTime(item.created_at),
    total: item.amount_minor / 100,
    currency: item.currency,
    status,
    email: item.customer_email ?? '',
  }
}

function formatCurrency(amount: number, currency = 'USD') {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency }).format(amount)
}

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
] as const

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
  const routeNavigate = useNavigate()
  const [page, setPage] = useState<Page>('overview')
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [selectedConversation, setSelectedConversation] = useState('')
  const [orders, setOrders] = useState<Order[]>([])
  const [catalogProducts, setCatalogProducts] = useState<CatalogProduct[]>([])
  const catalogRevision = useRef(0)
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [selectedOrder, setSelectedOrder] = useState<string | null>(null)
  const [integrations, setIntegrations] = useState<Integration[]>([])
  const [agentConfig, setAgentConfig] = useState<AgentConfig | null>(null)
  const [agentConfigEtag, setAgentConfigEtag] = useState<string | null>(null)
  const [business, setBusiness] = useState<Business | null>(null)
  const [sessionReady, setSessionReady] = useState(false)
  const [workspaceLoading, setWorkspaceLoading] = useState(true)
  const [workspaceError, setWorkspaceError] = useState('')
  const [userName, setUserName] = useState('Workspace member')
  const [workspaceName, setWorkspaceName] = useState('')
  const [workspaceCreating, setWorkspaceCreating] = useState(false)
  const [resourceErrors, setResourceErrors] = useState<string[]>([])
  const [overviewMetrics, setOverviewMetrics] = useState<DashboardSummaryApi['metrics']>({})
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchTerm, setSearchTerm] = useState('')
  const [reply, setReply] = useState('')
  const [toast, setToast] = useState('')
  const [conversationFilter, setConversationFilter] = useState<'All' | ConversationStatus>('All')
  const [orderFilter, setOrderFilter] = useState('All orders')

  const currentConversation = conversations.find((item) => item.id === selectedConversation)
  const activeOrder = orders.find((item) => item.id === selectedOrder)
  const pendingApprovals = approvals.filter((item) => item.status === 'pending').length
  const connections: Record<Connection, boolean> = {
    WooCommerce: integrations.some((item) => item.provider === 'woocommerce' && item.status === 'connected'),
    Shopify: integrations.some((item) => item.provider === 'shopify' && item.status === 'connected'),
    Telegram: integrations.some((item) => item.provider === 'telegram' && item.status === 'connected'),
    PayPal: integrations.some((item) => item.provider === 'paypal' && item.status === 'connected'),
  }

  useEffect(() => {
    let active = true
    async function loadBusinesses() {
      if (!isSupabaseConfigured()) {
        setWorkspaceError('Authentication is not configured. Set the Supabase URL and public anon key to continue.')
        setWorkspaceLoading(false)
        return
      }
      try {
        const { data: { session }, error } = await getSupabaseClient().auth.getSession()
        if (error) throw error
        if (!session) {
          routeNavigate('/login', { replace: true })
          return
        }
        const metadataName = session.user.user_metadata.full_name ?? session.user.user_metadata.name
        setUserName(typeof metadataName === 'string' && metadataName.trim()
          ? metadataName.trim()
          : session.user.email ?? 'Workspace member')
        setSessionReady(true)
        const response = await apiRequest<Business[]>('/businesses')
        if (!active) return
        const preferredId = window.localStorage.getItem('reactant.activeBusinessId')
        const selected = response.find((item) => item.id === preferredId) ?? response[0] ?? null
        setBusiness(selected)
        if (selected) window.localStorage.setItem('reactant.activeBusinessId', selected.id)
      } catch (error) {
        if (active) setWorkspaceError(error instanceof Error ? error.message : 'Could not load your workspace.')
      } finally {
        if (active) setWorkspaceLoading(false)
      }
    }
    void loadBusinesses()
    return () => { active = false }
  }, [routeNavigate])

  useEffect(() => {
    if (!business) return
    let active = true
    const failures: string[] = []
    const recordFailure = (name: string, reason: unknown) => {
      failures.push(`${name}: ${reason instanceof Error ? reason.message : 'could not load'}`)
    }
    const requestedCatalogRevision = catalogRevision.current
    const requests: Promise<unknown>[] = []
    if (page === 'overview') {
      requests.push(
        apiRequest<DashboardSummaryApi>(businessPath(business.id, '/dashboard/summary')).then((summary) => {
          if (active) setOverviewMetrics(summary.metrics)
        }).catch((reason: unknown) => recordFailure('Overview', reason)),
      )
    }
    if (page === 'inbox') {
      requests.push(apiRequest<ConversationApi[]>(businessPath(business.id, '/conversations?limit=100')).then((rows) => {
        if (!active) return
        setConversations(rows.map(mapConversation))
        if (rows[0]) setSelectedConversation((current) => current || rows[0].id)
      }).catch((reason: unknown) => recordFailure('Conversations', reason)))
    }
    if (page === 'catalog') {
      requests.push(apiRequest<ProductApi[]>(businessPath(business.id, '/products?limit=100'), { cache: 'no-store' })
        .then((rows) => rows.map((product) => mapCatalogProduct(product)))
        .then((rows) => {
          if (active && catalogRevision.current === requestedCatalogRevision) setCatalogProducts(rows)
        }).catch((reason: unknown) => recordFailure('Catalog', reason)))
    }
    if (page === 'orders') {
      requests.push(apiRequest<OrderApi[]>(businessPath(business.id, '/orders?limit=100')).then((rows) => {
        if (active) setOrders(rows.map(mapOrder))
      }).catch((reason: unknown) => recordFailure('Orders', reason)))
    }
    if (page === 'approvals' || page === 'owner-assistant') {
      requests.push(apiRequest<Approval[]>(businessPath(business.id, '/approvals?status=pending&limit=100')).then((rows) => {
        if (active) setApprovals(rows)
      }).catch((reason: unknown) => recordFailure('Approvals', reason)))
    }
    if (page === 'integrations' || page === 'settings' || page === 'agent') {
      requests.push(apiRequest<Integration[]>(businessPath(business.id, '/integrations')).then((rows) => {
        if (active) setIntegrations(rows)
      }).catch((reason: unknown) => recordFailure('Integrations', reason)))
    }
    if (page === 'agent') {
      requests.push(apiRequestWithHeaders<AgentConfig>(businessPath(business.id, '/agent')).then(({ data, headers }) => {
        if (active) {
          setAgentConfig(data)
          setAgentConfigEtag(headers.get('ETag'))
        }
      }).catch((reason: unknown) => recordFailure('Business Agent', reason)))
    }
    void Promise.all(requests).then(() => {
      if (active) setResourceErrors(failures)
    })
    return () => { active = false }
  }, [business, page])

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

  const updateBusiness = useCallback((updated: Business) => {
    setBusiness((current) => current ? { ...current, ...updated } : updated)
  }, [])

  async function sendReply(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!reply.trim() || !business || !selectedConversation) return
    try {
      const message = await apiRequest<{ sender_type: 'customer' | 'agent' | 'staff'; text: string; created_at: string }>(
        businessPath(business.id, `/conversations/${selectedConversation}/messages`),
        {
          method: 'POST',
          headers: { 'Idempotency-Key': newIdempotencyKey() },
          body: JSON.stringify({ text: reply.trim(), visibility: 'customer' }),
        },
      )
      setConversations((items) => items.map((item) => item.id === selectedConversation
        ? { ...item, preview: message.text, time: displayTime(message.created_at), status: 'Needs reply', messages: [...item.messages, { from: 'staff', text: message.text, time: displayTime(message.created_at) }] }
        : item))
      setReply('')
      setToast('Reply queued for delivery')
    } catch (error) {
      setToast(error instanceof Error ? error.message : 'The reply could not be sent.')
    }
  }

  async function setConversationStatus(id: string, status: ConversationStatus) {
    if (!business) return
    const apiStatus = status === 'Needs reply' ? 'needs_reply' : status.toLowerCase()
    try {
      await apiRequest(businessPath(business.id, `/conversations/${id}`), {
        method: 'PATCH',
        body: JSON.stringify({ status: apiStatus }),
      })
      setConversations((items) => items.map((item) => item.id === id ? { ...item, status, unread: false } : item))
      setToast(status === 'Resolved' ? 'Conversation marked as resolved' : 'Conversation reopened')
    } catch (error) {
      setToast(error instanceof Error ? error.message : 'Conversation status could not be updated.')
    }
  }

  async function decideApproval(approvalId: string, decision: 'approved' | 'rejected') {
    if (!business) return
    try {
      const updated = await apiRequest<Approval>(businessPath(business.id, `/approvals/${approvalId}/decision`), {
        method: 'POST',
        headers: { 'Idempotency-Key': newIdempotencyKey() },
        body: JSON.stringify({ decision }),
      })
      setApprovals((items) => items.map((item) => item.id === updated.id ? updated : item))
      setToast(decision === 'approved' ? 'Approval submitted' : 'Approval declined')
    } catch (error) {
      setToast(error instanceof Error ? error.message : 'The approval decision could not be submitted.')
    }
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

  async function openConversation(id: string) {
    if (!business) return
    setSelectedConversation(id)
    setPage('inbox')
    setSearchOpen(false)
    setSearchTerm('')
    try {
      const [, messages] = await Promise.all([
        apiRequest(businessPath(business.id, `/conversations/${id}/read`), { method: 'POST' }),
        apiRequest<{ sender_type: 'customer' | 'agent' | 'staff'; text: string; created_at: string }[]>(businessPath(business.id, `/conversations/${id}/messages?limit=100`)),
      ])
      setConversations((items) => items.map((item) => item.id === id
        ? {
            ...item,
            unread: false,
            messages: messages.map((message) => ({
              from: message.sender_type,
              text: message.text,
              time: displayTime(message.created_at),
            })),
          }
        : item))
    } catch (error) {
      setToast(error instanceof Error ? error.message : 'The conversation could not be loaded.')
    }
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

  async function createWorkspace(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!workspaceName.trim()) return
    setWorkspaceCreating(true)
    setWorkspaceError('')
    try {
      const created = await apiRequest<Business>('/businesses', {
        method: 'POST',
        body: JSON.stringify({ name: workspaceName.trim(), currency: 'USD', timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC' }),
      })
      setBusiness(created)
      window.localStorage.setItem('reactant.activeBusinessId', created.id)
    } catch (error) {
      setWorkspaceError(error instanceof Error ? error.message : 'Workspace could not be created.')
    } finally {
      setWorkspaceCreating(false)
    }
  }

  async function signOut() {
    try {
      const { error } = await getSupabaseClient().auth.signOut()
      if (error) throw error
      routeNavigate('/login', { replace: true })
    } catch (error) {
      setToast(error instanceof Error ? error.message : 'Sign out could not be completed.')
    }
  }

  if (workspaceLoading || !sessionReady) {
    return <WorkspaceGate message={workspaceError || 'Loading your workspace...'} />
  }
  if (workspaceError && !business) {
    return <WorkspaceGate message={workspaceError} onRetry={() => window.location.reload()} />
  }
  if (!business) {
    return (
      <WorkspaceGate>
        <form className="workspace-create-form" onSubmit={(event) => void createWorkspace(event)}>
          <h1>Create your business workspace</h1>
          <p>Your workspace keeps your business data, channels, and agent settings together.</p>
          <label className="field-label" htmlFor="workspace-name">Business name</label>
          <TextField.Root id="workspace-name" value={workspaceName} onChange={(event) => setWorkspaceName(event.target.value)} required maxLength={160} />
          {workspaceError && <p className="api-error" role="alert">{workspaceError}</p>}
          <Button type="submit" disabled={workspaceCreating || !workspaceName.trim()}>{workspaceCreating ? 'Creating workspace...' : 'Create workspace'}</Button>
        </form>
      </WorkspaceGate>
    )
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
          inboxCount={conversations.filter((conversation) => conversation.unread).length}
          approvalCount={pendingApprovals}
          businessName={business.name}
          userName={userName}
          role={business.role}
        />
        <div className="workspace">
          <header className="topbar">
            <Button className="mobile-menu" variant="ghost" aria-label="Open navigation" onClick={() => setMobileNavOpen(true)}>
              <List size={21} />
            </Button>
            <div className="breadcrumb">
              <span className="breadcrumb-workspace">{business.name}</span>
              <CaretRight size={14} />
              <span>{pageTitles[page]}</span>
            </div>
            <div className="topbar-actions">
              <Button variant="surface" className="search-trigger" onClick={() => { setSearchTerm(''); setSearchOpen(true) }}>
                <MagnifyingGlass size={16} />
                <span>Search</span>
                <kbd>⌘ K</kbd>
              </Button>
              <button className="icon-button notification-button" aria-label="Notifications" onClick={() => setToast('Notifications will appear here when available.')}>
                <Bell size={19} />
                <span className="notification-mark" />
              </button>
              <button className="profile-button" aria-label="Sign out" onClick={() => void signOut()}>
                <span className="profile-avatar">{nameInitials(business.name)}</span>
                <CaretDown size={14} />
              </button>
            </div>
          </header>

          <main className="main-content">
            {resourceErrors.length > 0 && (
              <div className="api-error resource-errors" role="alert">
                <strong>Some workspace data could not be loaded.</strong>
                <ul>{resourceErrors.map((error) => <li key={error}>{error}</li>)}</ul>
              </div>
            )}
            {page === 'overview' && (
              <Overview
                agentEnabled={agentConfig?.enabled ?? false}
                conversations={conversations}
                orders={orders}
                overviewMetrics={overviewMetrics}
                catalogProductCount={catalogProducts.length}
                connections={connections}
                navigate={navigate}
                openConversation={openConversation}
                openOrder={openOrder}
                paymentConnected={connections.PayPal}
                pendingApprovals={pendingApprovals}
                businessName={business.name}
                currency={business.currency}
              />
            )}
            {page === 'inbox' && (
              <Inbox
                conversations={visibleConversations}
                allConversations={conversations}
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
                businessId={business.id}
                products={catalogProducts}
                setProducts={setCatalogProducts}
                onMutationStart={() => { catalogRevision.current += 1 }}
                notify={setToast}
                currency={business.currency}
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
              />
            )}
            {page === 'approvals' && <Approvals approvals={approvals} decide={decideApproval} />}
            {page === 'integrations' && (
              <Integrations businessId={business.id} integrations={integrations} setIntegrations={setIntegrations} notify={setToast} />
            )}
            {page === 'agent' && (
              <AgentSettings
                businessId={business.id}
                config={agentConfig}
                etag={agentConfigEtag}
                setConfig={setAgentConfig}
                setEtag={setAgentConfigEtag}
                notify={setToast}
                paymentConnected={connections.PayPal}
                integrations={integrations}
              />
            )}
            {page === 'settings' && (
              <WorkspaceSettings
                businessId={business.id}
                business={business}
                integrations={integrations}
                notify={setToast}
                onBusinessUpdated={updateBusiness}
                openIntegrations={() => navigate('integrations')}
              />
            )}
            {page === 'owner-assistant' && <OwnerAssistant businessId={business.id} notify={setToast} decideApproval={decideApproval} approvals={approvals} />}
          </main>
        </div>

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

function Sidebar({ page, navigate, mobileNavOpen, close, inboxCount, approvalCount, businessName, userName, role }: {
  page: Page
  navigate: (page: Page) => void
  mobileNavOpen: boolean
  close: () => void
  inboxCount: number
  approvalCount: number
  businessName: string
  userName: string
  role: Business['role']
}) {
  return (
    <aside className={`sidebar ${mobileNavOpen ? 'sidebar-open' : ''}`}>
      <div className="brand-row">
        <BrandMark className="brand-mark" />
        <span className="brand-name">reactant</span>
        <button className="mobile-close" aria-label="Close navigation" onClick={close}><X size={19} /></button>
      </div>
      <button className="workspace-switcher" onClick={() => navigate('overview')}>
        <span className="workspace-avatar">{nameInitials(businessName).slice(0, 1)}</span>
        <span className="workspace-name"><strong>{businessName}</strong><small>Business workspace</small></span>
        <CaretDown size={15} />
      </button>
      <nav className="main-navigation" aria-label="Main navigation">
        <p className="nav-section-label">Workspace</p>
        {navigation.slice(0, 5).map((item) => <NavItem key={item.page} item={item} active={page === item.page} navigate={navigate} count={item.page === 'inbox' ? inboxCount : item.page === 'approvals' ? approvalCount : undefined} />)}
        <p className="nav-section-label manage-label">Manage</p>
        {navigation.slice(5).map((item) => <NavItem key={item.page} item={item} active={page === item.page} navigate={navigate} />)}
      </nav>
      <div className="sidebar-bottom">
        <div className="sidebar-user">
          <span className="user-avatar">{nameInitials(userName)}</span>
          <span className="user-meta"><strong>{userName}</strong><small>{role?.replace('_', ' ') ?? 'Workspace member'}</small></span>
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

function WorkspaceGate({ message, onRetry, children }: { message?: string; onRetry?: () => void; children?: React.ReactNode }) {
  return (
    <Theme accentColor="grass" grayColor="slate" radius="medium" scaling="100%" appearance="light">
      <main className="workspace-gate">
        <Link className="public-brand" to="/"><BrandMark className="public-brand-mark" /><span>reactant</span></Link>
        <section className="panel workspace-gate-panel">
          {children ?? <><h1>Your workspace</h1><p role={onRetry ? 'alert' : 'status'}>{message}</p>{onRetry && <Button onClick={onRetry}>Try again</Button>}</>}
        </section>
      </main>
    </Theme>
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
  overviewMetrics,
  catalogProductCount,
  connections,
  navigate,
  openConversation,
  openOrder,
  paymentConnected,
  pendingApprovals,
  businessName,
  currency,
}: {
  agentEnabled: boolean
  conversations: Conversation[]
  orders: Order[]
  overviewMetrics: DashboardSummaryApi['metrics']
  catalogProductCount: number
  connections: Record<Connection, boolean>
  navigate: (page: Page) => void
  openConversation: (id: string) => void
  openOrder: (id: string) => void
  paymentConnected: boolean
  pendingApprovals: number
  businessName: string
  currency: string
}) {
  const paidOrders = orders.filter((order) => order.status === 'Paid' || order.status === 'Processing').length
  const needsReply = conversations.filter((conversation) => conversation.status === 'Needs reply').length
  const sales = orders.filter((order) => order.status === 'Paid' || order.status === 'Processing').reduce((total, order) => total + order.total, 0)
  const productSourceReady = connections.WooCommerce || catalogProductCount > 0
  const productSourceDescription = catalogProductCount > 0
    ? `${connections.WooCommerce ? 'WooCommerce sync and ' : ''}${catalogProductCount} Reactant catalog ${catalogProductCount === 1 ? 'product' : 'products'}`
    : 'Products synced from WooCommerce'
  const completedSetupSteps = Number(productSourceReady) + Number(connections.Telegram) + Number(paymentConnected)
  const setupComplete = completedSetupSteps === 3
  return (
    <div className="page-body overview-page">
      <PageHeading
        title={`Welcome to ${businessName}`}
        description="Here is the latest activity available in your workspace."
        action={<Button onClick={() => navigate('integrations')}><Plus size={17} /> Connect a channel</Button>}
      />

      <section className="metric-grid" aria-label="Business summary">
        <Metric label="Conversations" value={String(overviewMetrics.conversations ?? conversations.length)} change="In this workspace" icon={ChatCircleDots} />
        <Metric label="Orders" value={String(overviewMetrics.orders ?? orders.length)} change={`${paidOrders} paid or processing`} icon={ShoppingBagOpen} />
        <Metric label="Sales" value={formatCurrency(sales, currency)} change="Paid or processing orders" icon={CreditCard} />
        <Metric label="Need your attention" value={`${needsReply + (overviewMetrics.pending_approvals ?? pendingApprovals)}`} change={`${needsReply} conversations · ${overviewMetrics.pending_approvals ?? pendingApprovals} approvals`} icon={WarningCircle} attention />
      </section>

      <section className="overview-primary-grid">
        <div className="panel activity-panel">
          <div className="panel-heading">
            <div><h2>Recent conversations</h2><p>Customer messages that may need your attention</p></div>
            <button className="text-link" onClick={() => navigate('inbox')}>Open inbox <ArrowRight size={15} /></button>
          </div>
          <div className="conversation-preview-list">
            {conversations.length === 0 && <p className="empty-list">Customer conversations will appear here when a channel receives a message.</p>}
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
            {orders.length === 0 && <p className="empty-list">Orders from connected channels will appear here.</p>}
            {orders.slice(0, 3).map((order) => (
              <button className="latest-order-row" key={order.id} onClick={() => openOrder(order.id)}>
                <span className="order-icon"><ShoppingBagOpen size={18} /></span>
                <span className="latest-order-copy"><strong>{order.customer}</strong><small>{order.id} <span>·</span> {order.item}</small></span>
                <span className="latest-order-total">{formatCurrency(order.total, order.currency)}</span>
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
              : <button className="setup-item setup-next" onClick={() => navigate('integrations')}><span className="setup-step-icon"><CreditCard size={16} /></span><span><strong>Set up payments</strong><small>Connect PayPal to accept payments</small></span><ArrowRight size={16} /></button>}
          </div>
        </div>
      </section>
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
  businessId,
  products,
  setProducts,
  onMutationStart,
  notify,
  currency,
}: {
  businessId: string
  products: CatalogProduct[]
  setProducts: React.Dispatch<React.SetStateAction<CatalogProduct[]>>
  onMutationStart: () => void
  notify: (message: string) => void
  currency: string
}) {
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [category, setCategory] = useState('')
  const [price, setPrice] = useState('')
  const [stock, setStock] = useState('')
  const [images, setImages] = useState<string[]>([])
  const [imageAssetIds, setImageAssetIds] = useState<string[]>([])
  const [imageFiles, setImageFiles] = useState<(File | null)[]>([])
  const [readingImages, setReadingImages] = useState(false)
  const [savingProduct, setSavingProduct] = useState(false)
  const [successMessage, setSuccessMessage] = useState('')
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
    setImageAssetIds(product?.imageAssetIds ?? [])
    setImageFiles(product?.images.map(() => null) ?? [])
    setAgentCanShare(product?.agentCanShare ?? true)
    setFormError('')
    setSuccessMessage('')
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
      setImageAssetIds((current) => [...current, ...selected.map(() => '')])
      setImageFiles((current) => [...current, ...selected])
      setFormError('')
    } catch (error) {
      setFormError(error instanceof Error ? error.message : 'Could not load the selected images.')
    } finally {
      setReadingImages(false)
    }
  }

  async function saveProduct(event: React.FormEvent<HTMLFormElement>) {
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
    setSavingProduct(true)
    setFormError('')
    setSuccessMessage('')
    onMutationStart()
    try {
      const assetIds = [...imageAssetIds]
      for (let index = 0; index < images.length; index += 1) {
        const file = imageFiles[index]
        if (!file || assetIds[index]) continue
        const upload = await apiRequest<{
          asset_id: string
          upload_url: string
          required_headers: Record<string, string>
        }>(businessPath(businessId, '/media/uploads'), {
          method: 'POST',
          body: JSON.stringify({
            file_name: file.name,
            content_type: file.type,
            size_bytes: file.size,
            purpose: 'catalog_product',
          }),
        })
        const uploadUrl = new URL(upload.upload_url)
        if (uploadUrl.protocol !== 'https:' && uploadUrl.hostname !== 'localhost' && uploadUrl.hostname !== '127.0.0.1') {
          throw new Error('The image service returned an insecure upload URL.')
        }
        const uploaded = await fetch(upload.upload_url, {
          method: 'PUT',
          headers: upload.required_headers,
          body: file,
          credentials: 'omit',
          referrerPolicy: 'no-referrer',
        })
        if (!uploaded.ok) throw new Error(`Could not upload ${file.name} (HTTP ${uploaded.status}).`)
        await apiRequest(businessPath(businessId, `/media/${encodeURIComponent(upload.asset_id)}/complete`), { method: 'POST' })
        assetIds[index] = upload.asset_id
        setImageAssetIds([...assetIds])
        setImageFiles((current) => current.map((item, currentIndex) => currentIndex === index ? null : item))
      }

      const body = {
        name: name.trim(),
        description: description.trim() || null,
        category: category.trim() || null,
        price_minor: Math.round(parsedPrice * 100),
        currency: editingId ? products.find((item) => item.id === editingId)?.currency ?? currency : currency,
        stock_quantity: parsedStock,
        status: 'active',
        agent_enabled: agentCanShare,
        image_asset_ids: assetIds,
      }
      const saved = await apiRequest<ProductApi>(
        businessPath(businessId, editingId ? `/products/${encodeURIComponent(editingId)}` : '/products'),
        {
          method: editingId ? 'PATCH' : 'POST',
          body: JSON.stringify(body),
        },
      )
      const product = mapCatalogProduct(saved, images)
      setProducts((current) => editingId
        ? current.map((item) => item.id === editingId ? product : item)
        : [product, ...current],
      )
      setDialogOpen(false)
      const message = editingId ? 'Product updated and visible in your catalog.' : 'Product added and visible in your catalog.'
      setSuccessMessage(message)
      notify(message)
    } catch (error) {
      setFormError(error instanceof Error ? error.message : 'The product could not be saved.')
    } finally {
      setSavingProduct(false)
    }
  }

  async function toggleAgentAccess(product: CatalogProduct) {
    try {
      onMutationStart()
      const updated = await apiRequest<ProductApi>(
        businessPath(businessId, `/products/${encodeURIComponent(product.id)}`),
        { method: 'PATCH', body: JSON.stringify({ agent_enabled: !product.agentCanShare }) },
      )
      const mapped = mapCatalogProduct(updated, product.images)
      setProducts((current) => current.map((item) => item.id === product.id ? mapped : item))
    } catch (error) {
      notify(error instanceof Error ? error.message : 'Agent access could not be updated.')
    }
  }

  async function removeProduct(product: CatalogProduct) {
    if (!window.confirm(`Remove ${product.name} from the catalog?`)) return
    try {
      onMutationStart()
      await apiRequest(businessPath(businessId, `/products/${encodeURIComponent(product.id)}`), { method: 'DELETE' })
      setProducts((current) => current.filter((item) => item.id !== product.id))
      notify(`${product.name} removed from the catalog`)
    } catch (error) {
      notify(error instanceof Error ? error.message : 'The product could not be removed.')
    }
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
      {successMessage && <p className="catalog-success-message" role="status"><CheckCircle size={16} /> {successMessage}</p>}

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
                {product.images[0]
                  ? <img src={product.images[0]} alt={product.name} />
                  : <div className="catalog-image-placeholder" aria-label="Product image unavailable"><ImageSquare size={28} /></div>}
                {product.images.length > 1 && <span className="catalog-image-count"><ImageSquare size={13} /> {product.images.length} photos</span>}
                {!product.available && <span className="catalog-product-state">Out of stock</span>}
              </div>
              <div className="catalog-product-details">
                <div className="catalog-product-title-row">
                  <div>
                    <h2>{product.name}</h2>
                    <div className="catalog-product-labels">
                      {product.category && <span className="catalog-category">{product.category}</span>}
                    </div>
                  </div>
                  <strong className="catalog-price">{formatCurrency(product.price, product.currency)}</strong>
                </div>
                {product.description && <p className="catalog-product-description">{product.description}</p>}
                <div className="catalog-product-meta">
                  <span>{product.stock === null ? 'Stock not tracked' : `${product.stock} in stock`}</span>
                  <button
                    className={`catalog-agent-access ${product.agentCanShare ? 'catalog-agent-enabled' : ''}`}
                    onClick={() => { void toggleAgentAccess(product) }}
                    aria-pressed={product.agentCanShare}
                  >
                    <Robot size={14} /> {product.agentCanShare ? 'Agent can share' : 'Hidden from agent'}
                  </button>
                </div>
                <div className="catalog-product-actions">
                  <Button variant="soft" color="gray" onClick={() => openProductForm(product)}>Edit product</Button>
                  <button className="catalog-remove-button" onClick={() => { void removeProduct(product) }} aria-label={`Remove ${product.name}`}><Trash size={16} /></button>
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
                <label className="field-label" htmlFor="catalog-price">Price ({editingId ? products.find((item) => item.id === editingId)?.currency ?? 'USD' : 'USD'})</label>
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
                      <button type="button" onClick={() => {
                        setImages((current) => current.filter((_, imageIndex) => imageIndex !== index))
                        setImageAssetIds((current) => current.filter((_, imageIndex) => imageIndex !== index))
                        setImageFiles((current) => current.filter((_, imageIndex) => imageIndex !== index))
                      }} aria-label={`Remove product photo ${index + 1}`}><X size={14} /></button>
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
              <Button type="submit" disabled={savingProduct || readingImages}>{savingProduct ? 'Saving...' : editingId ? 'Save changes' : 'Add to catalog'}</Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Root>
    </div>
  )
}

function Inbox({
  conversations,
  allConversations,
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
  allConversations: Conversation[]
  selectedConversation?: Conversation
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
  const filterOptions = [
    { label: 'All', count: allConversations.length },
    { label: 'Needs reply', count: allConversations.filter((conversation) => conversation.status === 'Needs reply').length },
    { label: 'Open', count: allConversations.filter((conversation) => conversation.status === 'Open').length },
    { label: 'Resolved', count: allConversations.filter((conversation) => conversation.status === 'Resolved').length },
  ] as const

  return (
    <div className="page-body inbox-page">
      <PageHeading title="Inbox" description="Keep every customer conversation moving." />
      <div className="inbox-layout">
        <section className="panel inbox-list-panel" aria-label="Conversations">
          <div className="inbox-list-toolbar">
            <TextField.Root placeholder="Search conversations" value={search} onChange={(event) => setSearch(event.target.value)} aria-label="Search conversations">
              <TextField.Slot><MagnifyingGlass size={16} /></TextField.Slot>
            </TextField.Root>
            <Button variant="soft" color="gray" aria-label={filter === 'All' ? 'Show conversations needing a reply' : 'Show all conversations'} onClick={() => setFilter(filter === 'All' ? 'Needs reply' : 'All')}><Funnel size={16} /></Button>
          </div>
          <div className="inbox-filters" role="tablist" aria-label="Filter conversations">
            {filterOptions.map(({ label, count }) => (
              <button key={label} className={`inbox-filter ${filter === label ? 'inbox-filter-active' : ''}`} onClick={() => setFilter(label)} role="tab" aria-selected={filter === label}>
                <span>{label}</span><span className="inbox-filter-count">{count}</span>
              </button>
            ))}
          </div>
          <div className="inbox-conversation-list">
            {conversations.length === 0 && <div className="empty-list">{allConversations.length === 0 ? 'Conversations will appear here when customers contact your connected channels.' : 'No conversations match this filter.'}</div>}
            {conversations.map((conversation) => (
              <button className={`inbox-conversation ${selectedConversation?.id === conversation.id ? 'inbox-conversation-selected' : ''}`} key={conversation.id} onClick={() => setSelected(conversation.id)}>
                <Avatar initials={conversation.initials} color={conversation.color} />
                <span className="inbox-conversation-info">
                  <span className="inbox-conversation-name"><strong>{conversation.name}</strong><small>{conversation.time}</small></span>
                  <span className="inbox-conversation-preview">{conversation.preview}</span>
                  <span className="inbox-conversation-tags"><span className="channel-tag"><ChatCircleDots size={12} /> {conversation.channel}</span>{conversation.status === 'Needs reply' && <span className="needs-reply-label">Needs reply</span>}</span>
                </span>
                {conversation.unread && <span className="unread-indicator" aria-label="Unread" />}
              </button>
            ))}
          </div>
        </section>

        <section className="panel conversation-panel" aria-label={selectedConversation ? `Conversation with ${selectedConversation.name}` : 'Conversation details'}>
          {!selectedConversation ? (
            <div className="empty-state"><span className="empty-state-icon"><ChatCircleDots size={24} /></span><h2>Select a conversation</h2><p>Choose a customer conversation to review its messages.</p></div>
          ) : <>
          <div className="conversation-header">
            <div className="conversation-person">
              <Avatar initials={selectedConversation.initials} color={selectedConversation.color} />
              <div><strong>{selectedConversation.name}</strong><span><ChatCircleDots size={13} /> {selectedConversation.channel} · {selectedConversation.id}</span></div>
            </div>
            <div className="conversation-header-actions">
              <Badge color={selectedConversation.status === 'Needs reply' ? 'orange' : selectedConversation.status === 'Resolved' ? 'gray' : 'green'} variant="soft">{selectedConversation.status}</Badge>
            </div>
          </div>
          <div className="conversation-context">
            <button onClick={() => setStatus(selectedConversation.id, selectedConversation.status === 'Resolved' ? 'Open' : 'Resolved')}>
              {selectedConversation.status === 'Resolved' ? <ArrowLeft size={14} /> : <Check size={14} />}
              {selectedConversation.status === 'Resolved' ? 'Reopen' : 'Resolve'}
            </button>
          </div>
          <div className="message-thread">
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
            <div className="composer-footer"><span>Replying as a workspace member</span><Button type="submit" disabled={!reply.trim()}><PaperPlaneTilt size={15} /> Send reply</Button></div>
          </form>
          </>}
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
}: {
  orders: Order[]
  selectedOrder?: Order
  filter: string
  setFilter: (filter: string) => void
  search: string
  setSearch: (value: string) => void
  selectOrder: (id: string | null) => void
}) {
  return (
    <div className="page-body orders-page">
      <PageHeading title="Orders" description="Track orders and payment status in one place." />
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
                  <td className="total-cell">{formatCurrency(order.total, order.currency)}</td>
                  <td><OrderStatus status={order.status} /></td>
                  <td><button className="icon-button row-more" aria-label={`More actions for ${order.id}`} onClick={(event) => { event.stopPropagation(); selectOrder(order.id) }}><DotsThree size={20} /></button></td>
                </tr>
              ))}
              {orders.length === 0 && <tr><td className="table-empty-cell" colSpan={7}>No orders found. Try another filter or search.</td></tr>}
            </tbody>
          </table>
        </div>
        <div className="table-pagination"><span>{orders.length} orders loaded</span></div>
      </section>
      {selectedOrder && (
        <div className="order-detail-backdrop" onClick={() => selectOrder(null)}>
          <aside className="order-detail-drawer" onClick={(event) => event.stopPropagation()} aria-label={`Order details for ${selectedOrder.id}`}>
            <div className="drawer-heading"><div><span className="drawer-eyebrow">Order details</span><h2>{selectedOrder.id}</h2></div><button className="icon-button" aria-label="Close order details" onClick={() => selectOrder(null)}><X size={19} /></button></div>
            <OrderStatus status={selectedOrder.status} />
            <div className="detail-section"><h3>Customer</h3><div className="detail-customer"><Avatar initials={selectedOrder.initials} color={colorForInitials(selectedOrder.initials)} /><span><strong>{selectedOrder.customer}</strong><small>{selectedOrder.email}</small></span></div></div>
            <div className="detail-section"><h3>Items</h3><div className="detail-item"><span className="order-icon"><ShoppingBagOpen size={18} /></span><span><strong>{selectedOrder.item}</strong></span><strong>{formatCurrency(selectedOrder.total, selectedOrder.currency)}</strong></div></div>
            <div className="detail-section"><h3>Payment summary</h3><div className="summary-row"><span>Order amount</span><strong>{formatCurrency(selectedOrder.total, selectedOrder.currency)}</strong></div></div>
            <div className="detail-section"><h3>Timeline</h3><div className="order-timeline"><span className="timeline-icon"><CheckCircle size={16} /></span><span><strong>Order created</strong><small>{selectedOrder.date}</small></span></div></div>
            <Button variant="soft" color="gray" className="drawer-action" onClick={() => selectOrder(null)}>Close details</Button>
          </aside>
        </div>
      )}
    </div>
  )
}

function Approvals({ approvals, decide }: { approvals: Approval[]; decide: (id: string, decision: 'approved' | 'rejected') => Promise<void> }) {
  const pending = approvals.filter((item) => item.status === 'pending')
  return (
    <div className="page-body approvals-page">
      <PageHeading title="Approvals" description="Review sensitive actions before your agent proceeds." />
      <div className="approvals-summary">
        <div className="approval-summary-icon"><ShieldCheck size={20} /></div>
        <div><strong>{pending.length === 0 ? 'You’re all caught up' : `${pending.length} ${pending.length === 1 ? 'action needs' : 'actions need'} your review`}</strong><p>Orders and other sensitive actions wait here when approval is required.</p></div>
      </div>
      {pending.length > 0 && (
        <div className={`approval-list ${pending.length === 1 ? 'approval-list-single' : ''}`}>
          {pending.map((approval) => {
            const details = approval.impact.summary
            const customer = approval.impact.customer_name
            const amount = approval.impact.amount_minor
            const currency = approval.impact.currency
            return <ApprovalCard
              key={approval.id}
              title={approval.action_type.replaceAll('_', ' ')}
              subtitle={typeof details === 'string' ? details : 'The Business Agent is waiting for an authorized team member to review this action.'}
              customer={typeof customer === 'string' ? customer : 'Business Agent'}
              initials={nameInitials(typeof customer === 'string' ? customer : 'Business Agent')}
              amount={typeof amount === 'number' && typeof currency === 'string' ? formatCurrency(amount / 100, currency) : `Request ${approval.id}`}
              time={`Requested ${displayTime(approval.created_at)}`}
              onApprove={() => void decide(approval.id, 'approved')}
              onReject={() => void decide(approval.id, 'rejected')}
            />
          })}
        </div>
      )}
      {pending.length === 0 && <div className="empty-state"><span className="empty-state-icon"><CheckCircle size={25} /></span><h2>No pending approvals</h2><p>New requests will appear here when an action needs your review.</p></div>}
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

function Integrations({ businessId, integrations, setIntegrations, notify }: {
  businessId: string
  integrations: Integration[]
  setIntegrations: React.Dispatch<React.SetStateAction<Integration[]>>
  notify: (message: string) => void
}) {
  const [dialogProvider, setDialogProvider] = useState<Connection | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [telegramSetup, setTelegramSetup] = useState<TelegramSetup | null>(null)
  const providers: { provider: Connection; key: Integration['provider']; description: string; icon: Icon; category: string }[] = [
    { provider: 'WooCommerce', key: 'woocommerce', description: 'Sync products, stock, and orders from your online store.', icon: Storefront, category: 'Store' },
    { provider: 'Shopify', key: 'shopify', description: 'Import products and inventory from your Shopify store.', icon: Storefront, category: 'Store' },
    { provider: 'Telegram', key: 'telegram', description: 'Receive customer messages through your Telegram bot.', icon: TelegramLogo, category: 'Messaging' },
    { provider: 'PayPal', key: 'paypal', description: 'Create customer checkout sessions and verify payments.', icon: CreditCard, category: 'Payments' },
  ]

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    if (params.get('provider') !== 'shopify' || !params.get('integration')) return
    const result = params.get('integration')
    if (result === 'connected') {
      notify('Shopify connected successfully.')
    } else {
      setError('Shopify authorization did not complete. Try connecting the store again.')
    }
    window.history.replaceState({}, '', `${window.location.pathname}${window.location.hash}`)
  }, [notify])

  async function refreshIntegration(integrationId: string) {
    const updated = await apiRequest<Integration>(businessPath(businessId, `/integrations/${integrationId}`))
    setIntegrations((items) => items.map((item) => item.id === integrationId ? updated : item))
    return updated
  }

  async function createConnection(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!dialogProvider) return
    const form = event.currentTarget
    const formData = new FormData(form)
    if (dialogProvider === 'Shopify') {
      setSaving(true)
      setError('')
      try {
        const shop = String(formData.get('shop_domain') ?? '').trim()
        const authorization = await apiRequest<{ authorization_url: string }>(
          businessPath(businessId, '/integrations/shopify/authorization') + `?shop=${encodeURIComponent(shop)}`,
          { method: 'POST' },
        )
        window.location.assign(authorization.authorization_url)
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : 'Shopify authorization could not be started.')
        setSaving(false)
      }
      return
    }
    const credentials = dialogProvider === 'WooCommerce'
      ? {
          store_url: String(formData.get('store_url') ?? '').trim(),
          consumer_key: String(formData.get('consumer_key') ?? ''),
          consumer_secret: String(formData.get('consumer_secret') ?? ''),
          webhook_secret: createWebhookSecret(),
        }
      : dialogProvider === 'Telegram'
        ? { bot_token: String(formData.get('bot_token') ?? ''), webhook_secret: createWebhookSecret() }
        : {
            consumer_key: String(formData.get('paypal_client_id') ?? ''),
            consumer_secret: String(formData.get('paypal_client_secret') ?? ''),
            webhook_id: String(formData.get('paypal_webhook_id') ?? ''),
          }
    setSaving(true)
    setError('')
    try {
      const created = await apiRequest<Integration>(businessPath(businessId, '/integrations'), {
        method: 'POST',
        body: JSON.stringify({ provider: dialogProvider.toLowerCase(), credentials }),
      })
      setIntegrations((items) => [created, ...items.filter((item) => item.id !== created.id)])
      form.reset()
      setDialogProvider(null)
      if (created.provider === 'telegram') {
        void testConnection(created)
      } else if (created.provider === 'woocommerce') {
        const connected = await apiRequest<Integration>(
          businessPath(businessId, `/integrations/${created.id}/test`),
          { method: 'POST' },
        )
        setIntegrations((items) => items.map((item) => item.id === connected.id ? connected : item))
        notify(`${dialogProvider} connected successfully.`)
      } else {
        notify(`${dialogProvider} credentials were submitted. Verify the connection before relying on it.`)
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The integration could not be connected.')
    } finally {
      setSaving(false)
    }
  }

  async function testConnection(integration: Integration) {
    setSaving(true)
    setError('')
    try {
      await apiRequest(businessPath(businessId, `/integrations/${integration.id}/test`), { method: 'POST' })
      await refreshIntegration(integration.id)
      if (integration.provider === 'telegram') {
        const setup = await apiRequest<TelegramSetup>(
          businessPath(businessId, `/integrations/${integration.id}/telegram-setup`),
        )
        setTelegramSetup(setup)
        notify(`Telegram connected to @${setup.bot_username}.`)
        return
      }
      notify(`${integration.provider} connection test completed.`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The connection test failed.')
    } finally {
      setSaving(false)
    }
  }

  async function syncConnection(integration: Integration) {
    setSaving(true)
    setError('')
    try {
      await apiRequest(businessPath(businessId, `/integrations/${integration.id}/sync`), { method: 'POST' })
      await refreshIntegration(integration.id)
      notify(`${integration.provider} sync was queued.`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The sync could not be started.')
    } finally {
      setSaving(false)
    }
  }

  async function disconnect(integration: Integration) {
    if (!window.confirm(`Disconnect ${integration.provider}? Reactant will stop syncing this account.`)) return
    setSaving(true)
    setError('')
    try {
      await apiRequest(businessPath(businessId, `/integrations/${integration.id}`), { method: 'DELETE' })
      setIntegrations((items) => items.filter((item) => item.id !== integration.id))
      notify(`${integration.provider} was disconnected.`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The integration could not be disconnected.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="page-body integrations-page">
      <PageHeading title="Integrations" description="Connect and manage the services your workspace uses." />
      <div className="integration-callout"><span className="callout-icon"><ShieldCheck size={20} /></span><span><strong>Your accounts stay yours.</strong><small>Connections use limited access, and you can disconnect them at any time.</small></span></div>
      <div className="integration-grid">
        {providers.map((provider) => {
          const IconComponent = provider.icon
          const connection = integrations.find((item) => item.provider === provider.key && item.status !== 'disconnected')
          const connected = connection?.status === 'connected'
          return (
            <article className={`panel integration-card ${connected ? 'integration-connected' : ''}`} key={provider.key}>
              <div className="integration-card-top"><span className={`integration-icon integration-icon-${provider.provider.toLowerCase()}`}><IconComponent size={22} /></span><Badge color="gray" variant="soft">{provider.category}</Badge></div>
              <h2>{provider.provider}</h2>
              <p>{provider.description}</p>
              {connection && (
                <div className="integration-status">
                  {connected ? <CheckCircle size={15} weight="fill" /> : <WarningCircle size={15} />}
                  <span>{connection.status.replaceAll('_', ' ')}</span>
                  {connection.last_success_at && <small>Last synced {displayTime(connection.last_success_at)}</small>}
                  {connection.last_error && <small className="integration-error-text">{connection.last_error}</small>}
                </div>
              )}
              {provider.key === 'telegram' && telegramSetup && connection?.id === integrations.find((item) => item.provider === 'telegram')?.id && (
                <div className="integration-setup-details">
                  <strong>Telegram webhook ready</strong>
                  <small>Bot: @{telegramSetup.bot_username || telegramSetup.bot_name}</small>
                  <small>{telegramSetup.webhook_url}</small>
                </div>
              )}
              <div className="integration-card-actions">
                {connection
                  ? <>
                      {provider.key !== 'telegram' && provider.key !== 'shopify' && <Button variant="soft" color="gray" disabled={saving} onClick={() => void testConnection(connection)}>Test</Button>}
                      {provider.key === 'woocommerce' && <Button variant="soft" color="gray" disabled={saving} onClick={() => void syncConnection(connection)}>Sync now</Button>}
                      <Button variant="soft" color="red" disabled={saving} onClick={() => void disconnect(connection)}>Disconnect</Button>
                    </>
                  : provider.key === 'paypal'
                    ? <Button onClick={() => { setError(''); setDialogProvider('PayPal') }}>Connect</Button>
                    : <Button onClick={() => { setError(''); setDialogProvider(provider.provider) }}>Connect</Button>}
              </div>
            </article>
          )
        })}
      </div>
      {error && <p className="api-error" role="alert">{error}</p>}
      <Dialog.Root open={dialogProvider !== null} onOpenChange={(open) => { if (!open && !saving) setDialogProvider(null) }}>
        <Dialog.Content className="dialog-content">
          <Dialog.Title className="dialog-title">Connect {dialogProvider}</Dialog.Title>
          <Dialog.Description className="dialog-description">
            {dialogProvider === 'WooCommerce'
              ? 'Use an HTTPS store URL and WooCommerce REST API keys with only the permissions Reactant needs.'
              : dialogProvider === 'Shopify'
                ? 'Enter your store domain. Shopify will securely ask you to approve the connection.'
              : dialogProvider === 'Telegram'
                ? 'Create a bot with Telegram BotFather, then paste its token. Keep the token private.'
                : 'Use the REST app credentials and webhook ID from PayPal. Reactant uses these only to create checkout sessions and verify customer payments.'}
          </Dialog.Description>
          <form className="connection-form" onSubmit={(event) => void createConnection(event)}>
            {dialogProvider === 'WooCommerce' ? (
              <>
                <label className="field-label" htmlFor="connection-store-url">Store URL</label>
                <TextField.Root id="connection-store-url" name="store_url" type="url" placeholder="https://yourstore.com" pattern="https://.*" required />
                <label className="field-label" htmlFor="connection-consumer-key">REST API consumer key</label>
                <TextField.Root id="connection-consumer-key" name="consumer_key" type="password" autoComplete="off" required />
                <label className="field-label" htmlFor="connection-consumer-secret">REST API consumer secret</label>
                <TextField.Root id="connection-consumer-secret" name="consumer_secret" type="password" autoComplete="off" required />
                <p className="form-note">Create the keys in WooCommerce under Settings, Advanced, REST API. Credentials are sent only to Reactant over HTTPS.</p>
              </>
            ) : dialogProvider === 'Shopify' ? (
              <>
                <label className="field-label" htmlFor="connection-shop-domain">Shopify store domain</label>
                <TextField.Root id="connection-shop-domain" name="shop_domain" placeholder="your-store.myshopify.com" required />
                <p className="form-note">You will review the requested access in Shopify. Reactant never asks you to paste an Admin API token.</p>
              </>
            ) : dialogProvider === 'Telegram' ? (
              <>
                <label className="field-label" htmlFor="connection-bot-token">Telegram bot token</label>
                <TextField.Root id="connection-bot-token" name="bot_token" type="password" autoComplete="off" required />
                <p className="form-note">Create a bot with @BotFather. Reactant configures the webhook; never share this token with customers.</p>
              </>
            ) : (
              <>
                <label className="field-label" htmlFor="paypal-client-id">PayPal REST app client ID</label>
                <TextField.Root id="paypal-client-id" name="paypal_client_id" type="password" autoComplete="off" required />
                <label className="field-label" htmlFor="paypal-client-secret">PayPal REST app secret</label>
                <TextField.Root id="paypal-client-secret" name="paypal_client_secret" type="password" autoComplete="off" required />
                <label className="field-label" htmlFor="paypal-webhook-id">PayPal webhook ID</label>
                <TextField.Root id="paypal-webhook-id" name="paypal_webhook_id" autoComplete="off" required />
                <p className="form-note">Create an app and webhook in PayPal Developer. Reactant never receives permission to access your balance or move funds.</p>
              </>
            )}
            {error && <p className="api-error" role="alert">{error}</p>}
            <div className="dialog-actions">
              <Button type="button" variant="soft" color="gray" disabled={saving} onClick={() => setDialogProvider(null)}>Cancel</Button>
              <Button type="submit" disabled={saving}>{saving ? 'Connecting...' : dialogProvider === 'Shopify' ? 'Continue to Shopify' : 'Save credentials'}</Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Root>
    </div>
  )
}

function AgentSettings({ businessId, config, etag, setConfig, setEtag, notify, paymentConnected, integrations }: {
  businessId: string
  config: AgentConfig | null
  etag: string | null
  setConfig: React.Dispatch<React.SetStateAction<AgentConfig | null>>
  setEtag: (etag: string | null) => void
  notify: (message: string) => void
  paymentConnected: boolean
  integrations: Integration[]
}) {
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  async function saveAgent() {
    if (!config || !etag) {
      setError('Agent settings are not ready to save. Reload the workspace and try again.')
      return
    }
    setSaving(true)
    setError('')
    try {
      const { data, headers } = await apiRequestWithHeaders<AgentConfig>(businessPath(businessId, '/agent'), {
        method: 'PATCH',
        headers: { 'If-Match': etag },
        body: JSON.stringify({
          enabled: config.enabled,
          business_context: config.business_context,
          tone: config.tone,
          handoff_rule: config.handoff_rule,
          permissions: config.permissions,
          approval_policy: {
            ...config.approval_policy,
              checkout_threshold_minor: config.approval_policy.checkout_threshold_minor,
          },
        }),
      })
      setConfig(data)
      setEtag(headers.get('ETag'))
      notify('Business Agent settings saved.')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Agent settings could not be saved.')
    } finally {
      setSaving(false)
    }
  }

  const updateConfig = (update: Partial<AgentConfig>) => setConfig((current) => current ? { ...current, ...update } : current)
  const permissionRows: { key: keyof AgentConfig['permissions']; title: string; description: string; blocked?: boolean }[] = [
    { key: 'answer_product_questions', title: 'Answer product questions', description: 'Use active products from your connected store and catalog.' },
    { key: 'share_product_images', title: 'Share product images', description: 'Send product photos to customers through supported channels.' },
    { key: 'create_carts_and_orders', title: 'Build carts and prepare orders', description: 'Validate product, quantity, price, and availability before order creation.' },
    { key: 'create_paypal_checkout', title: 'Create PayPal checkout links', description: paymentConnected ? 'Create customer checkout sessions. The agent cannot access balances or send payouts.' : 'Connect PayPal before enabling customer checkout links.', blocked: !paymentConnected },
  ]

  if (!config) {
    return <div className="page-body"><PageHeading title="Business agent" description="Agent configuration is not available from the API yet." /></div>
  }

  return (
    <div className="page-body agent-page">
      <PageHeading title="Business agent" description="Set how your agent speaks and which business actions it is allowed to take." action={<Button onClick={() => void saveAgent()} disabled={saving}>{saving ? 'Saving...' : 'Save changes'}</Button>} />
      {error && <p className="api-error" role="alert">{error}</p>}
      <div className="agent-page-layout">
        <div className="agent-settings-column">
          <section className="panel agent-control-panel">
            <div className="agent-control-heading"><div className="agent-avatar"><Robot size={23} weight="duotone" /></div><div><h2>Customer support agent</h2><p>Shared across your connected channels</p></div><div className="agent-toggle"><span>{config.enabled ? 'Active' : 'Paused'}</span><Switch checked={config.enabled} onCheckedChange={(enabled) => updateConfig({ enabled })} aria-label="Enable business agent" /></div></div>
            <div className={`agent-state-note ${config.enabled ? '' : 'agent-paused-note'}`}><span className={`agent-indicator ${config.enabled ? 'is-on' : 'is-off'}`} /><span>{config.enabled ? `Agent status: ${config.status}. Changes take effect after saving.` : 'Your agent is paused. Save to apply this change.'}</span></div>
          </section>
          <section className="panel settings-section">
            <div className="settings-section-heading"><h2>Business profile</h2><p>Give the agent accurate context to represent your business.</p></div>
            <label className="field-label" htmlFor="business-description">About your business</label>
            <textarea id="business-description" className="settings-textarea" value={config.business_context} onChange={(event) => updateConfig({ business_context: event.target.value })} rows={4} maxLength={20000} />
            <div className="settings-two-column">
              <div><label className="field-label" htmlFor="agent-tone">Tone of voice</label><select className="settings-select" id="agent-tone" value={config.tone} onChange={(event) => updateConfig({ tone: event.target.value })}><option value="warm_helpful">Warm and helpful</option><option value="direct_concise">Direct and concise</option><option value="professional">Professional</option></select></div>
              <div><label className="field-label" htmlFor="handoff-rule">Human handoff</label><select className="settings-select" id="handoff-rule" value={config.handoff_rule} onChange={(event) => updateConfig({ handoff_rule: event.target.value })}><option value="when_uncertain">When the agent is unsure</option><option value="when_customer_asks">When a customer asks</option><option value="always_offer_human">Always offer a person</option></select></div>
            </div>
          </section>
          <section className="panel settings-section">
            <div className="settings-section-heading"><h2>What your agent can do</h2><p>Backend policy checks remain authoritative for every action.</p></div>
            <div className="permission-list">
              {permissionRows.map((row) => (
                <PermissionRow key={row.key} title={row.title} description={row.description} checked={config.permissions[row.key]} disabled={row.blocked} onChange={(checked) => updateConfig({ permissions: { ...config.permissions, [row.key]: checked } })} />
              ))}
              <PermissionRow title="Require approval for checkout" description="Hold checkout creation until an authorized team member approves it." checked={config.approval_policy.require_approval_for_checkout} onChange={(checked) => updateConfig({ approval_policy: { ...config.approval_policy, require_approval_for_checkout: checked } })} />
            </div>
            {config.approval_policy.require_approval_for_checkout && (
              <div className="approval-threshold">
                <label className="field-label" htmlFor="checkout-threshold">Require approval above (USD)</label>
                <div className="threshold-input-row"><span>$</span><input id="checkout-threshold" type="number" min="0" step="0.01" value={config.approval_policy.checkout_threshold_minor === null ? '' : (config.approval_policy.checkout_threshold_minor / 100).toString()} onChange={(event) => {
                  const rawValue = event.target.value
                  const amount = rawValue.trim() === '' ? null : Number(rawValue)
                  if (amount === null || (Number.isFinite(amount) && amount >= 0)) {
                    updateConfig({ approval_policy: { ...config.approval_policy, checkout_threshold_minor: amount === null ? null : Math.round(amount * 100) } })
                  }
                }} placeholder="Every checkout" aria-describedby="checkout-threshold-help" /></div>
                <small id="checkout-threshold-help">Leave blank to require approval for every checkout.</small>
              </div>
            )}
          </section>
        </div>
        <aside className="agent-settings-aside">
          <section className="panel agent-summary-panel">
            <h2>Connected channels</h2>
            {[
              { provider: 'telegram', title: 'Telegram', icon: TelegramLogo },
              { provider: 'woocommerce', title: 'WooCommerce', icon: Storefront },
              { provider: 'paypal', title: 'PayPal', icon: CreditCard },
            ].map((channel) => {
              const status = integrations.find((item) => item.provider === channel.provider)?.status
              const IconComponent = channel.icon
              return <div className="connected-channel-row" key={channel.provider}><IconComponent size={18} /><span>{channel.title}</span><Badge color={status === 'connected' ? 'green' : 'gray'} variant="soft">{status ?? 'Not connected'}</Badge></div>
            })}
          </section>
          <section className="panel agent-guidelines-panel">
            <span className="guideline-icon"><ShieldCheck size={19} /></span><h2>Built to be careful</h2><p>Checkout permissions do not bypass approval policy, current stock, price, or payment verification.</p>
            <button className="text-link" onClick={() => notify('Safety checks are enforced by the Reactant API before an action runs.')}>How permissions work <ArrowUpRight size={14} /></button>
          </section>
        </aside>
      </div>
    </div>
  )
}

function OwnerAssistant({ businessId, notify, decideApproval, approvals }: { businessId: string; notify: (message: string) => void; decideApproval: (id: string, decision: 'approved' | 'rejected') => Promise<void>; approvals: Approval[] }) {
  const [messages, setMessages] = useState<OwnerMessage[] | null>(null)
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [runtimeStatus, setRuntimeStatus] = useState<'loading' | 'ready' | 'unavailable'>('loading')
  const [pendingRuns, setPendingRuns] = useState<string[]>([])

  const loadMessages = useCallback(async () => {
    try {
      const thread = await apiRequest<{ thread: { id: string }; messages: OwnerMessage[] }>(businessPath(businessId, '/owner-assistant/thread'))
      setError('')
      setMessages([...thread.messages].reverse())
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The private agent thread could not be loaded.')
    }
  }, [businessId])

  useEffect(() => { void loadMessages() }, [loadMessages])

  useEffect(() => {
    let active = true
    void apiRequest<{ available: boolean; reason: string }>(businessPath(businessId, '/owner-assistant/status'))
      .then((status) => {
        if (!active) return
        setRuntimeStatus(status.available ? 'ready' : 'unavailable')
      })
      .catch(() => { if (active) setRuntimeStatus('unavailable') })
    return () => { active = false }
  }, [businessId])

  useEffect(() => {
    if (pendingRuns.length === 0) return
    const timer = window.setInterval(() => {
      void Promise.all(pendingRuns.map(async (runId) => {
        const run = await apiRequest<{ status: 'queued' | 'running' | 'succeeded' | 'failed'; error_code: string | null }>(
          businessPath(businessId, `/owner-assistant/runs/${runId}`),
        )
        if (run.status === 'succeeded') {
          await loadMessages()
          return runId
        }
        if (run.status === 'failed') {
          setError(run.error_code ? `The agent could not complete the request (${run.error_code}).` : 'The agent could not complete the request.')
          return runId
        }
        return null
      })).then((completed) => {
        const finished = new Set(completed.filter((runId): runId is string => runId !== null))
        if (finished.size > 0) setPendingRuns((runs) => runs.filter((runId) => !finished.has(runId)))
      }).catch(() => {
        setError('The agent status could not be refreshed. The message remains queued.')
      })
    }, 2000)
    return () => window.clearInterval(timer)
  }, [businessId, loadMessages, pendingRuns])

  async function sendOwnerMessage(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const text = draft.trim()
    if (!text || sending) return
    const clientMessageId = newIdempotencyKey()
    setSending(true)
    setError('')
    try {
      const accepted = await apiRequest<{ message: OwnerMessage; agent_run_id: string; agent_run_status: 'queued' | 'running' }>(businessPath(businessId, '/owner-assistant/messages'), {
        method: 'POST',
        headers: { 'Idempotency-Key': clientMessageId },
        body: JSON.stringify({ text, client_message_id: clientMessageId }),
      })
      setMessages((items) => [...(items ?? []), accepted.message])
      setPendingRuns((runs) => [...runs, accepted.agent_run_id])
      setDraft('')
      notify('Message queued for the Business Agent.')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Your message could not be sent.')
    } finally {
      setSending(false)
    }
  }

  async function decideOwnerApproval(approvalId: string, decision: 'approved' | 'rejected') {
    await decideApproval(approvalId, decision)
    await loadMessages()
  }

  return (
    <div className="page-body owner-assistant-page">
      <PageHeading
        title="Agent messages"
        description="A private conversation with your Business Agent, separate from customer chats."
      />
      <div className="owner-channel-notice">
        <span className="owner-channel-notice-icon"><ShieldCheck size={19} /></span>
        <div><strong>Only your workspace team can see this conversation.</strong><p>Customers will never receive messages from this channel. Use it to answer agent questions, review requests, and adjust how it handles your business.</p></div>
      </div>
      <section className="owner-thread panel" aria-label="Private agent conversation">
        <header className="owner-thread-header">
          <div className="owner-agent-identity">
            <span className="owner-agent-avatar"><Robot size={20} weight="duotone" /></span>
            <span><strong>Reactant business agent</strong><small>Private to this workspace</small></span>
          </div>
          <Badge color={error || runtimeStatus === 'unavailable' ? 'red' : runtimeStatus === 'ready' ? 'green' : 'gray'} variant="soft">
            {error || runtimeStatus === 'unavailable' ? 'Unavailable' : runtimeStatus === 'ready' ? 'Ready' : 'Loading'}
          </Badge>
        </header>
        <div className="owner-thread-context">
          <ChatCircleDots size={17} />
          <span>
            This is the owner channel. Customer conversations remain in the Inbox.
            {runtimeStatus === 'unavailable' && ' Your agent is not ready yet. Check the agent setup to enable replies.'}
          </span>
        </div>
        <div className="owner-message-list" aria-live="polite">
          {messages === null && !error && <p className="empty-list">Loading private messages...</p>}
          {messages?.length === 0 && !error && <p className="empty-list">No private messages yet. Send a note to give the agent business context.</p>}
          {error && <p className="api-error" role="alert">{error}</p>}
          {(messages ?? []).map((message) => (
            <article key={message.id} className={`owner-message owner-message-${message.sender_type === 'agent' ? 'agent' : 'owner'}`}>
              <span className="owner-message-author">{message.sender_type === 'agent' ? message.display_name : 'You'} <time>{displayTime(message.created_at)}</time></span>
              <p>{message.text}</p>
              {message.kind === 'approval_request' && message.approval_id && (
                <div className="owner-approval-request">
                  {(() => {
                    const approval = approvals.find((item) => item.id === message.approval_id)
                    return (
                      <>
                  <div className="owner-approval-summary">
                    <span className="owner-approval-icon"><CreditCard size={17} /></span>
                    <span><strong>Approval request</strong><small>Request {message.approval_id}</small></span>
                    <Badge color={approval?.status === 'pending' ? 'orange' : 'gray'} variant="soft">{approval?.status ?? 'Status unavailable'}</Badge>
                  </div>
                        {approval?.status === 'pending' && <div className="owner-approval-actions">
                          <Button variant="soft" color="gray" onClick={() => void decideOwnerApproval(message.approval_id!, 'rejected')}>Decline</Button>
                          <Button onClick={() => void decideOwnerApproval(message.approval_id!, 'approved')}><Check size={15} /> Approve request</Button>
                        </div>}
                      </>
                    )
                  })()}
                </div>
              )}
            </article>
          ))}
        </div>
        <form className="owner-message-composer" onSubmit={(event) => void sendOwnerMessage(event)}>
          <label className="sr-only" htmlFor="owner-agent-message">Message your business agent</label>
          <textarea
            id="owner-agent-message"
            rows={3}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                event.currentTarget.form?.requestSubmit()
              }
            }}
            placeholder={runtimeStatus === 'ready' ? 'Ask your Business Agent anything...' : 'Your agent is unavailable. Set it up to continue.'}
            disabled={runtimeStatus !== 'ready' || sending}
            aria-describedby="owner-composer-help"
          />
          <div className="owner-composer-footer">
            <small id="owner-composer-help">Enter to send · Shift+Enter for a new line · Private to this workspace.</small>
            <Button type="submit" disabled={!draft.trim() || sending || runtimeStatus !== 'ready'}><PaperPlaneTilt size={16} /> {sending ? 'Sending...' : 'Send message'}</Button>
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
