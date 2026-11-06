import { useState } from 'react'
import {
  ArrowRight,
  ArrowUpRight,
  ChatCircleDots,
  Check,
  CheckCircle,
  CreditCard,
  DotsThree,
  Eye,
  EyeSlash,
  GearSix,
  ImageSquare,
  InstagramLogo,
  List,
  MagnifyingGlass,
  Package,
  PaperPlaneTilt,
  Robot,
  ShieldCheck,
  Storefront,
  TelegramLogo,
  WhatsappLogo,
  X,
} from '@phosphor-icons/react'
import { Link } from 'react-router-dom'
import BrandMark from './BrandMark'
import './PublicSite.css'

const currentYear = new Date().getFullYear()

export function LandingPage() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)

  return (
    <div className="public-site">
      <header className="public-nav">
        <Link className="public-brand" to="/" aria-label="Reactant home">
          <BrandMark className="public-brand-mark" />
          <span>reactant</span>
        </Link>
        <nav id="public-primary-navigation" className={`public-nav-links ${mobileMenuOpen ? 'public-nav-links-open' : ''}`} aria-label="Main navigation">
          <a href="#platform" onClick={() => setMobileMenuOpen(false)}>Platform</a>
          <a href="#integrations" onClick={() => setMobileMenuOpen(false)}>Integrations</a>
          <a href="#solutions" onClick={() => setMobileMenuOpen(false)}>Solutions</a>
          <a href="#developers" onClick={() => setMobileMenuOpen(false)}>Developers</a>
        </nav>
        <div className="public-nav-actions">
          <Link className="public-login-link" to="/login">Sign in</Link>
          <Link className="public-button public-button-small" to="/signup">Get started <ArrowRight size={15} /></Link>
        </div>
        <button
          className="public-menu-toggle"
          type="button"
          aria-label={mobileMenuOpen ? 'Close navigation' : 'Open navigation'}
          aria-expanded={mobileMenuOpen}
          aria-controls="public-primary-navigation"
          onClick={() => setMobileMenuOpen((open) => !open)}
        >
          {mobileMenuOpen ? <X size={21} /> : <List size={21} />}
        </button>
      </header>

      <main>
        <section className="public-hero" aria-labelledby="public-hero-title">
          <div className="public-hero-copy">
            <p className="public-eyebrow"><span className="eyebrow-line" /> The operating layer for your business</p>
            <h1 id="public-hero-title"><span>Your business, connected.</span><em>Work keeps moving.</em></h1>
            <p className="public-hero-description">Connect the tools you use. Give your Business Agent context to help customers and keep work moving.</p>
            <div className="public-hero-actions">
              <Link className="public-button" to="/signup">Get started <ArrowRight size={17} /></Link>
              <a className="public-text-link" href="#platform">Explore the platform <ArrowUpRight size={16} /></a>
            </div>
          </div>
          <div className="public-hero-image-wrap"><ConnectedSystemsShowcase /></div>
        </section>

        <section className="operating-problem" aria-labelledby="problem-title">
          <div className="section-heading problem-heading">
            <h2 id="problem-title">When your systems are disconnected, customer questions and orders can slip through.</h2>
            <p>Every unanswered message can mean a missed sale. Reactant brings conversations, product details, payments, and order workflows into one connected flow.</p>
          </div>
          <div className="disconnected-flow" aria-label="Reactant connects customer channels, storefronts, payments, and order operations">
            <div className="disconnected-group">
              <span className="disconnected-label">Where customers reach you</span>
              <div><ChatCircleDots size={17} /> Messages</div>
              <div><Storefront size={17} /> Storefront</div>
            </div>
            <div className="disconnected-connector" aria-hidden="true"><span /><ArrowRight size={18} /><span /></div>
            <div className="reactant-core">
              <BrandMark className="reactant-core-mark" />
              <span><strong>Reactant</strong><small>One operational layer</small></span>
            </div>
            <div className="disconnected-connector" aria-hidden="true"><span /><ArrowRight size={18} /><span /></div>
            <div className="disconnected-group">
              <span className="disconnected-label">What needs to happen</span>
              <div><Package size={17} /> Products & stock</div>
              <div><CreditCard size={17} /> Orders & checkout</div>
            </div>
          </div>
          <p className="problem-close">Your tools stay in place. Reactant helps them work together.</p>
        </section>

        <section className="public-layer-section" id="platform" aria-labelledby="platform-title">
          <div className="section-heading">
            <h2 id="platform-title">One intelligent layer across your business.</h2>
            <p>Reactant connects your systems, gives the Business Agent useful context, and keeps actions within the permissions you set.</p>
          </div>
          <div className="capability-rows">
            <article><span className="capability-index">01</span><h3>Connect</h3><p>Bring together your storefront, customer channels, and payment provider.</p><Storefront size={21} /></article>
            <article><span className="capability-index">02</span><h3>Understand</h3><p>Ground answers in your products, policies, orders, and customer conversations.</p><MagnifyingGlass size={21} /></article>
            <article><span className="capability-index">03</span><h3>Act</h3><p>Let the agent handle permitted tasks and ask you before sensitive actions.</p><GearSix size={21} /></article>
          </div>
        </section>

        <section className="public-commerce-section" id="agent" aria-labelledby="agent-title">
          <div className="commerce-copy">
            <p className="public-eyebrow"><span className="eyebrow-line" /> Customer conversations to commerce</p>
            <h2 id="agent-title">More than a chatbot. An agent grounded in your business.</h2>
            <p>It can find products, answer questions, check known availability, and prepare an order. Payment status is confirmed before an order is marked paid.</p>
            <ul className="commerce-capabilities">
              <li><Check size={16} /> Product answers from your connected store or catalog</li>
              <li><Check size={16} /> Product images, details, and availability checks</li>
              <li><Check size={16} /> PayPal checkout with merchant approval rules</li>
              <li><Check size={16} /> Human handoff when a request needs your team</li>
            </ul>
            <a className="public-text-link" href="#controls">See how you stay in control <ArrowRight size={16} /></a>
          </div>
          <CommerceJourneyShowcase />
        </section>

        <section className="public-integrations-section" id="integrations" aria-labelledby="integrations-title">
          <div className="section-heading integrations-heading">
            <h2 id="integrations-title">Start with the tools your business already uses.</h2>
            <p>Reactant is being built around a focused first set of commerce, messaging, and payment connections.</p>
          </div>
          <div className="integration-groups">
            <IntegrationGroup title="Commerce">
              <IntegrationItem icon={<Storefront size={18} />} name="WooCommerce" state="MVP" />
              <IntegrationItem icon={<Storefront size={18} />} name="Shopify" state="Planned" />
              <IntegrationItem icon={<Package size={18} />} name="Reactant catalog" state="MVP" />
            </IntegrationGroup>
            <IntegrationGroup title="Customer channels">
              <IntegrationItem icon={<TelegramLogo size={18} />} name="Telegram" state="MVP" />
              <IntegrationItem icon={<WhatsappLogo size={18} />} name="WhatsApp Business" state="Planned" />
              <IntegrationItem icon={<InstagramLogo size={18} />} name="Instagram & Messenger" state="Planned" />
              <IntegrationItem icon={<ChatCircleDots size={18} />} name="Website chat" state="Planned" />
            </IntegrationGroup>
            <IntegrationGroup title="Payments">
              <IntegrationItem icon={<CreditCard size={18} />} name="PayPal" state="MVP" />
            </IntegrationGroup>
          </div>
          <p className="integration-disclaimer">“MVP” marks initial product scope, not a live availability guarantee. Planned integrations are not available yet; provider features and merchant eligibility vary by country.</p>
        </section>

        <section className="platform-section" aria-labelledby="platform-architecture-title">
          <div className="platform-section-copy">
            <h2 id="platform-architecture-title">A platform, not another disconnected tool.</h2>
            <p>Reactant coordinates the agent, integrations, commerce workflows, business context, and operational controls in one place.</p>
            <a className="public-text-link" href="#how-it-works">How Reactant works <ArrowRight size={16} /></a>
          </div>
          <PlatformArchitecture />
          <div className="onboarding-flow" id="how-it-works" aria-label="How Reactant works">
            <div><span>Connect</span><p>Link your store, channels, and payment provider.</p></div>
            <div><span>Configure</span><p>Add business policies and operational preferences.</p></div>
            <div><span>Set permissions</span><p>Choose what the agent can do and when it must ask.</p></div>
            <div><span>Go live</span><p>Review activity and step in when needed.</p></div>
          </div>
        </section>

        <section className="public-controls-section" id="controls" aria-labelledby="controls-title">
          <div className="controls-copy">
            <h2 id="controls-title">Routine conversations keep moving. Decisions stay with you.</h2>
            <p>Whether you're busy with orders or off the clock, your agent can handle common requests around the clock. It follows the permissions you set, and sensitive requests can wait for your approval.</p>
            <ul className="commerce-capabilities">
              <li><Check size={16} /> Product search and common questions</li>
              <li><Check size={16} /> Order status and draft order workflows</li>
              <li><Check size={16} /> Approval for sensitive actions</li>
              <li><Check size={16} /> Separate private channel for agent-to-owner messages</li>
            </ul>
          </div>
          <OwnerMessagesShowcase />
        </section>

        <section className="solutions-section" id="solutions" aria-labelledby="solutions-title">
          <div className="section-heading">
            <h2 id="solutions-title">Built around how you sell and serve.</h2>
            <p>From a growing online shop to a business selling through messages, keep product questions and orders moving in one workflow.</p>
          </div>
          <div className="solution-list">
            <article><strong>Online retail</strong><span>Product discovery, order support, and checkout coordination.</span></article>
            <article><strong>Fashion and lifestyle</strong><span>Variants, sizing questions, stock checks, and product recommendations.</span></article>
            <article><strong>Social commerce</strong><span>Keep product photos and details ready even without a dedicated storefront.</span></article>
            <article><strong>Growing brands</strong><span>Bring more customer channels and operating context together over time.</span></article>
          </div>
          <div className="developer-note" id="developers">
            <div><p className="public-eyebrow"><span className="eyebrow-line" /> Designed to extend</p><h3>One operating foundation, built to grow.</h3></div>
            <p>Reactant's direction includes provider adapters, permission-aware agent tools, APIs, event workflows, and operational insights. Public developer capabilities and advanced analytics are not available yet.</p>
          </div>
        </section>

        <section className="public-cta" id="get-started">
          <div>
            <h2>Make every customer conversation count.</h2>
            <p>Connect the systems you use and give your business a more intelligent way to keep work moving.</p>
          </div>
          <Link className="public-button public-button-light" to="/signup">Get started <ArrowRight size={17} /></Link>
        </section>
      </main>

      <footer className="public-footer">
        <div className="footer-brand-block">
          <Link className="public-brand" to="/">
            <BrandMark className="public-brand-mark" />
            <span>reactant</span>
          </Link>
          <p>Connect your business tools. Keep customer conversations moving.</p>
        </div>
        <div className="footer-link-group"><strong>Platform</strong><a href="#agent">Business Agent</a><a href="#integrations">Integrations</a><a href="#platform">Commerce & payments</a></div>
        <div className="footer-link-group"><strong>Solutions</strong><a href="#solutions">Retail</a><a href="#solutions">Social commerce</a><a href="#solutions">Customer support</a></div>
        <div className="footer-link-group"><strong>Developers</strong><a href="#developers">Platform direction</a><a href="#developers">Integrations</a><a href="#get-started">Get started</a></div>
        <div className="footer-bottom"><span>© {currentYear} Reactant</span><div><Link to="/login">Sign in</Link><Link to="/signup">Get started</Link></div></div>
      </footer>
    </div>
  )
}

function ConnectedSystemsShowcase() {
  return (
    <div className="workflow-preview systems-preview" role="img" aria-label="Illustrative map of Reactant connecting a WooCommerce store, Telegram conversations, PayPal checkout, and a business catalog">
      <div className="systems-preview-heading"><span><strong>Your business systems</strong><small>Connected through Reactant</small></span><span className="systems-preview-sample">Illustrative</span></div>
      <div className="systems-map">
        <div className="systems-sources">
          <SystemNode icon={<Storefront size={18} />} name="WooCommerce" state="MVP" />
          <SystemNode icon={<TelegramLogo size={18} />} name="Telegram" state="MVP" />
          <SystemNode icon={<CreditCard size={18} />} name="PayPal" state="MVP" />
          <SystemNode icon={<Package size={18} />} name="Reactant catalog" state="MVP" />
        </div>
        <div className="systems-links" aria-hidden="true"><span /><span /><span /><span /></div>
        <div className="systems-agent">
          <span className="systems-agent-mark"><BrandMark /></span>
          <strong>Reactant</strong>
          <small>Business Agent + platform</small>
          <div className="systems-agent-capabilities"><span><Check size={12} /> Understand</span><span><Check size={12} /> Coordinate</span></div>
        </div>
        <div className="systems-links systems-links-out" aria-hidden="true"><span /><span /><span /></div>
        <div className="systems-outputs">
          <SystemNode icon={<ChatCircleDots size={18} />} name="Customer answers" />
          <SystemNode icon={<Package size={18} />} name="Product discovery" />
          <SystemNode icon={<CreditCard size={18} />} name="Order checkout" />
        </div>
      </div>
      <p className="systems-preview-note"><ShieldCheck size={14} /> Actions follow your business permissions</p>
    </div>
  )
}

function SystemNode({ icon, name, state }: { icon: React.ReactNode; name: string; state?: string }) {
  return (
    <div className="system-node">
      <span>{icon}</span>
      <strong>{name}</strong>
      {state && <small>{state}</small>}
    </div>
  )
}

function IntegrationGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <article className="integration-group">
      <div className="integration-group-heading"><h3>{title}</h3></div>
      <div className="integration-list">{children}</div>
    </article>
  )
}

function IntegrationItem({ icon, name, state }: { icon: React.ReactNode; name: string; state?: string }) {
  return (
    <div className="integration-item">
      <span className="integration-item-icon">{icon}</span>
      <strong>{name}</strong>
      {state && <small>{state}</small>}
    </div>
  )
}

function PlatformArchitecture() {
  const layers = [
    { title: 'Business Agent', description: 'Customer conversations, business context, permission-aware actions', icon: <Robot size={17} /> },
    { title: 'Commerce & payments', description: 'Catalog, products, orders, PayPal checkout', icon: <CreditCard size={17} /> },
    { title: 'Channels & integrations', description: 'WooCommerce and Telegram in the initial scope', icon: <Storefront size={17} /> },
    { title: 'Business knowledge', description: 'Products, policies, conversations, and operational context', icon: <Package size={17} /> },
    { title: 'Workflows & insights', description: 'Auditable actions now, advanced analytics planned', icon: <GearSix size={17} /> },
  ]

  return (
    <div className="architecture-preview" role="img" aria-label="Reactant platform layers combine the Business Agent, commerce and payments, channels, business knowledge, and workflows">
      <div className="architecture-heading"><BrandMark className="architecture-mark" /><span><strong>Reactant platform</strong><small>One coordinated system</small></span></div>
      <div className="architecture-layers">
        {layers.map((layer) => <div className="architecture-layer" key={layer.title}><span>{layer.icon}</span><div><strong>{layer.title}</strong><small>{layer.description}</small></div><CheckCircle size={16} /></div>)}
      </div>
    </div>
  )
}

function CommerceJourneyShowcase() {
  return (
    <div className="commerce-journey-preview" role="img" aria-label="Illustrative shopping conversation: customer asks about a product, agent checks product details, prepares checkout, and awaits verified payment">
      <div className="journey-preview-heading"><span className="journey-channel-icon"><TelegramLogo size={19} /></span><span><strong>Example customer conversation</strong><small>Illustrative workflow, not a live integration</small></span><DotsThree size={20} /></div>
      <div className="journey-chat">
        <div className="journey-customer-message">Do you have the Ceramic Pour-over Set in stock?</div>
        <div className="journey-agent-caption"><Robot size={13} /> Business Agent</div>
        <div className="journey-agent-message">I found it in the catalog. The set is listed at $620. Would you like me to prepare an order?</div>
        <div className="journey-product-result"><span className="journey-product-image"><ImageSquare size={22} /></span><span><strong>Ceramic Pour-over Set</strong><small>Product details from business catalog</small></span><span className="journey-product-price">$620</span></div>
        <div className="journey-customer-message journey-customer-confirm">Yes, please.</div>
        <div className="journey-checkout-message"><span><CreditCard size={15} /><strong>PayPal checkout</strong></span><small>Payment confirmation is verified before the order is marked paid.</small></div>
      </div>
      <div className="journey-steps" aria-label="Commerce workflow">
        <span><CheckCircle size={14} /> Find product</span><span><CheckCircle size={14} /> Prepare order</span><span><CreditCard size={14} /> Verify payment</span>
      </div>
    </div>
  )
}

function InboxShowcase() {
  return (
    <div className="workflow-preview inbox-preview" role="img" aria-label="Reactant inbox preview showing a customer product question and an agent response">
      <div className="workflow-preview-topbar">
        <div className="workflow-preview-brand"><BrandMark className="workflow-preview-mark" /><strong>reactant</strong></div>
        <span>Olive & Oak Studio</span>
        <DotsThree size={21} />
      </div>
      <div className="inbox-preview-layout">
        <aside className="inbox-preview-list">
          <div className="inbox-preview-title"><strong>Inbox</strong><span>3</span></div>
          <div className="inbox-preview-contact inbox-preview-contact-active">
            <span className="preview-avatar preview-avatar-coral">AM</span>
            <span><strong>Ama Mensah</strong><small>Do you have the linen set...</small></span>
            <time>2m</time>
          </div>
          <div className="inbox-preview-contact">
            <span className="preview-avatar preview-avatar-green">KB</span>
            <span><strong>Kojo Boateng</strong><small>I'll take the walnut one</small></span>
            <time>18m</time>
          </div>
          <div className="inbox-preview-contact">
            <span className="preview-avatar preview-avatar-blue">EO</span>
            <span><strong>Esi Owusu</strong><small>Help with delivery?</small></span>
            <time>42m</time>
          </div>
        </aside>
        <div className="inbox-preview-conversation">
          <div className="inbox-preview-person">
            <span className="preview-avatar preview-avatar-coral">AM</span>
            <span><strong>Ama Mensah</strong><small>Customer conversation</small></span>
          </div>
          <div className="preview-message preview-message-customer">Do you have the linen set in sand?</div>
          <div className="preview-agent-label"><Robot size={13} /> Reactant agent</div>
          <div className="preview-message preview-message-agent">The Coastline Linen Set comes in Queen and King. Which size would you like?</div>
          <div className="preview-product-link"><Package size={17} /><span><strong>Coastline Linen Set</strong><small>From $1,450</small></span><ArrowRight size={14} /></div>
          <div className="preview-composer"><span>Reply to Ama...</span><PaperPlaneTilt size={15} /></div>
        </div>
      </div>
    </div>
  )
}

function OwnerMessagesShowcase() {
  return (
    <div className="workflow-preview owner-preview" role="img" aria-label="Private Reactant agent message asking the business owner to approve a PayPal checkout">
      <div className="owner-preview-heading">
        <span className="owner-preview-icon"><Robot size={19} /></span>
        <span><strong>Agent messages</strong><small>Private conversation with your agent</small></span>
        <DotsThree size={21} />
      </div>
      <div className="owner-preview-thread">
        <div className="owner-preview-bubble">Stock and price are confirmed. A customer is ready to order the Ceramic Pour-over Set. May I prepare a checkout link?</div>
        <div className="owner-preview-approval">
          <div className="owner-preview-approval-title"><CreditCard size={16} /><strong>PayPal checkout request</strong></div>
          <div className="owner-preview-order"><span>RA-2085</span><strong>$620</strong></div>
          <div className="owner-preview-actions"><span>Review request</span><span><Check size={14} /> Approve</span></div>
        </div>
        <div className="owner-preview-security"><ShieldCheck size={15} /> Sensitive actions wait for your approval</div>
      </div>
    </div>
  )
}

export function AuthPage({ mode }: { mode: 'login' | 'signup' }) {
  const isSignup = mode === 'signup'
  const [formMessage, setFormMessage] = useState('')

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setFormMessage('Authentication is not connected yet. Your information was not sent or saved.')
  }

  return (
    <main className="auth-page">
      <section className="auth-visual">
        <Link className="public-brand" to="/">
          <BrandMark className="public-brand-mark" />
          <span>reactant</span>
        </Link>
        <div className="auth-visual-copy">
          <p className="public-eyebrow">Your business, connected</p>
          <h1>Good service should feel personal, even when it scales.</h1>
          <p>Bring your products, conversations, and team into one clear workspace.</p>
        </div>
        <div className="auth-showcase-wrap" aria-hidden="true"><InboxShowcase /></div>
      </section>
      <section className="auth-form-side">
        <Link className="auth-back-link" to="/">Back to Reactant</Link>
        <div className="auth-form-wrap">
          <BrandMark className="auth-mark" />
          <h2>{isSignup ? 'Create your account' : 'Welcome back'}</h2>
          <p>{isSignup ? 'Set up your workspace to bring your customer channels together.' : 'Log in to continue to your Reactant workspace.'}</p>
          <form className="auth-form" onSubmit={handleSubmit}>
            {isSignup && <FormField id="auth-name" label="Your name" type="text" autoComplete="name" />}
            <FormField id="auth-email" label="Work email" type="email" autoComplete="email" />
            <FormField id="auth-password" label="Password" type="password" autoComplete={isSignup ? 'new-password' : 'current-password'} />
            {!isSignup && <button className="auth-forgot-button" type="button" onClick={() => setFormMessage('Password recovery is not connected yet. No reset email was sent.')}>Forgot password?</button>}
            {formMessage && <p className="auth-preview-note" role="status">{formMessage}</p>}
            <button className="public-button auth-submit" type="submit">{isSignup ? 'Create account' : 'Log in'} <ArrowRight size={17} /></button>
          </form>
          <p className="auth-switch">{isSignup ? 'Already have an account?' : 'New to Reactant?'} <Link to={isSignup ? '/login' : '/signup'}>{isSignup ? 'Log in' : 'Create an account'}</Link></p>
          <p className="auth-privacy"><ShieldCheck size={15} /> This preview does not submit credentials to a server.</p>
        </div>
      </section>
    </main>
  )
}

function FormField({ id, label, type, autoComplete }: { id: string; label: string; type: string; autoComplete: string }) {
  const [passwordVisible, setPasswordVisible] = useState(false)
  const isPassword = type === 'password'

  return (
    <div className="auth-field">
      <label htmlFor={id}>{label}</label>
      <div className={isPassword ? 'auth-password-control' : undefined}>
        <input id={id} type={isPassword && passwordVisible ? 'text' : type} autoComplete={autoComplete} required minLength={isPassword ? 8 : undefined} />
        {isPassword && (
          <button
            className="auth-password-toggle"
            type="button"
            aria-label={passwordVisible ? 'Hide password' : 'Show password'}
            aria-pressed={passwordVisible}
            onClick={() => setPasswordVisible((visible) => !visible)}
          >
            {passwordVisible ? <EyeSlash size={18} /> : <Eye size={18} />}
          </button>
        )}
      </div>
      {isPassword && <small>Use at least 8 characters.</small>}
    </div>
  )
}

export function NotFoundPage() {
  return (
    <main className="not-found-page">
      <BrandMark className="public-brand-mark" />
      <h1>This page isn’t here.</h1>
      <p>The link may be outdated. Go back to the Reactant home page.</p>
      <Link className="public-button" to="/">Back to Reactant <ArrowRight size={17} /></Link>
    </main>
  )
}
