import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { ShieldCheck, WarningCircle } from '@phosphor-icons/react'
import { Badge, Button, Checkbox, Theme } from '@radix-ui/themes'
import { publicApiRequest } from './api'
import './AgentCardCheckout.css'

type CheckoutState =
  | 'awaiting_customer'
  | 'awaiting_payment'
  | 'payment_processing'
  | 'payment_pending'
  | 'payment_failed'
  | 'paid'
  | 'cancelled'
  | 'expired'
  | 'reconciliation'
  | 'receipt_generation'
  | 'receipt_issued'
  | 'receipt_delivered'

type Checkout = {
  checkout_id: string
  public_transaction_id: string
  business_name: string
  items: {
    product_id: string
    name: string
    description: string
    quantity: number
    unit_price_minor: number
    total_minor: number
    image_urls: string[]
  }[]
  subtotal_minor: number
  discount_total_minor: number
  tax_total_minor: number
  delivery_total_minor: number
  total_amount_minor: number
  currency: string
  status: CheckoutState
  expires_at: string
  authorization_required: boolean
}

type CheckoutStatus = {
  public_transaction_id: string
  status: CheckoutState
  amount_minor: number
  currency: string
  updated_at: string
  receipt_url: string | null
}

type PaymentResponse = {
  status: CheckoutState
  approval_url: string | null
}

function formatAmount(amountMinor: number, currency: string) {
  return new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(amountMinor / 100)
}

function stateMessage(state: CheckoutState) {
  switch (state) {
    case 'paid':
    case 'receipt_generation':
    case 'receipt_issued':
    case 'receipt_delivered':
      return 'Payment confirmed'
    case 'payment_pending':
    case 'payment_processing':
    case 'reconciliation':
      return 'Payment processing'
    case 'payment_failed':
      return 'Payment was not completed'
    case 'cancelled':
      return 'Checkout cancelled'
    case 'expired':
      return 'Checkout expired'
    default:
      return 'Review your checkout'
  }
}

export default function AgentCardCheckout() {
  const { token = '' } = useParams()
  const [searchParams] = useSearchParams()
  const [checkout, setCheckout] = useState<Checkout | null>(null)
  const [checkoutStatus, setCheckoutStatus] = useState<CheckoutStatus | null>(null)
  const [accepted, setAccepted] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const captureStarted = useRef(false)

  const loadCheckout = useCallback(async () => {
    const data = await publicApiRequest<Checkout>(`/agentcard/checkout/${encodeURIComponent(token)}`)
    setCheckout(data)
    setCheckoutStatus({
      public_transaction_id: data.public_transaction_id,
      status: data.status,
      amount_minor: data.total_amount_minor,
      currency: data.currency,
      updated_at: new Date().toISOString(),
      receipt_url: null,
    })
  }, [token])

  const loadStatus = useCallback(async () => {
    const data = await publicApiRequest<CheckoutStatus>(
      `/agentcard/checkout/${encodeURIComponent(token)}/status`,
    )
    setCheckoutStatus(data)
  }, [token])

  useEffect(() => {
    let active = true
    void loadCheckout().catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : 'This checkout could not be loaded.')
    })
    return () => { active = false }
  }, [loadCheckout])

  useEffect(() => {
    const providerOrderId = searchParams.get('paypal_order_id')
    if (!providerOrderId || captureStarted.current) return
    captureStarted.current = true
    let active = true
    setBusy(true)
    void publicApiRequest<PaymentResponse>(`/agentcard/checkout/${encodeURIComponent(token)}/capture`, {
      method: 'POST',
      body: JSON.stringify({ provider_order_id: providerOrderId }),
    }).then(async (result) => {
      if (!active) return
      setNotice(result.status === 'paid'
        ? 'PayPal confirmed your payment.'
        : 'PayPal has not confirmed the payment yet. You will see the verified status here.')
      await loadStatus()
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : 'Payment verification is still pending.')
    }).finally(() => {
      if (active) setBusy(false)
    })
    return () => { active = false }
  }, [loadStatus, searchParams, token])

  useEffect(() => {
    if (!checkoutStatus || !['payment_processing', 'payment_pending', 'reconciliation'].includes(checkoutStatus.status)) {
      return
    }
    const timer = window.setInterval(() => {
      void loadStatus().catch(() => undefined)
    }, 3000)
    return () => window.clearInterval(timer)
  }, [checkoutStatus, loadStatus])

  async function continueToPayment() {
    if (!checkout) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      if (checkout.status === 'awaiting_customer') {
        await publicApiRequest(`/agentcard/checkout/${encodeURIComponent(token)}/authorize`, {
          method: 'POST',
          body: JSON.stringify({ accepted: true }),
        })
      }
      const payment = await publicApiRequest<PaymentResponse>(
        `/agentcard/checkout/${encodeURIComponent(token)}/payment`,
        {
          method: 'POST',
          body: JSON.stringify({ accepted: true }),
        },
      )
      if (payment.approval_url) {
        window.location.assign(payment.approval_url)
        return
      }
      setNotice('Payment is being confirmed. Do not retry while this status is pending.')
      await loadStatus()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'PayPal could not start this payment.')
    } finally {
      setBusy(false)
    }
  }

  if (error && !checkout) {
    return (
      <CheckoutShell>
        <section className="agentcard-error">
          <WarningCircle size={26} />
          <h1>Checkout unavailable</h1>
          <p>{error}</p>
        </section>
      </CheckoutShell>
    )
  }

  if (!checkout) {
    return <CheckoutShell><p className="agentcard-loading">Loading your secure checkout…</p></CheckoutShell>
  }

  const state = checkoutStatus?.status ?? checkout.status
  const paid = ['paid', 'receipt_generation', 'receipt_issued', 'receipt_delivered'].includes(state)
  const waiting = ['payment_processing', 'payment_pending', 'reconciliation'].includes(state)
  const unavailable = ['cancelled', 'expired', 'payment_failed'].includes(state)
  const needsConsent = checkout.authorization_required && state === 'awaiting_customer'

  return (
    <CheckoutShell>
      <main className="agentcard-terminal">
        <header className="agentcard-brand">
          <span className="agentcard-logo"><ShieldCheck size={19} weight="duotone" /></span>
          <span>AgentCard <small>secure checkout</small></span>
          <Badge color={paid ? 'green' : waiting ? 'orange' : 'gray'} variant="soft">{stateMessage(state)}</Badge>
        </header>

        <section className="agentcard-merchant">
          <span className="agentcard-eyebrow">PAYING</span>
          <h1>{checkout.business_name}</h1>
          <p>Transaction {checkout.public_transaction_id}</p>
        </section>

        <section className="agentcard-items" aria-label="Order items">
          {checkout.items.map((item) => (
            <article className="agentcard-item" key={item.product_id}>
              {item.image_urls[0]
                ? <img src={item.image_urls[0]} alt={item.name} loading="lazy" />
                : <div className="agentcard-image-placeholder" aria-hidden="true" />}
              <div className="agentcard-item-copy">
                <strong>{item.name}</strong>
                {item.description && <p>{item.description}</p>}
                <small>Qty {item.quantity} · {formatAmount(item.unit_price_minor, checkout.currency)} each</small>
              </div>
              <b>{formatAmount(item.total_minor, checkout.currency)}</b>
            </article>
          ))}
        </section>

        <section className="agentcard-totals" aria-label="Checkout totals">
          <div><span>Subtotal</span><strong>{formatAmount(checkout.subtotal_minor, checkout.currency)}</strong></div>
          {checkout.discount_total_minor > 0 && <div><span>Discount</span><strong>−{formatAmount(checkout.discount_total_minor, checkout.currency)}</strong></div>}
          {checkout.tax_total_minor > 0 && <div><span>Tax</span><strong>{formatAmount(checkout.tax_total_minor, checkout.currency)}</strong></div>}
          {checkout.delivery_total_minor > 0 && <div><span>Delivery</span><strong>{formatAmount(checkout.delivery_total_minor, checkout.currency)}</strong></div>}
          <div className="agentcard-total"><span>Total due</span><strong>{formatAmount(checkout.total_amount_minor, checkout.currency)}</strong></div>
        </section>

        <section className="agentcard-payment-method">
          <span className="agentcard-paypal-mark">P</span>
          <span><strong>PayPal</strong><small>Payment is handled securely by PayPal.</small></span>
        </section>

        {needsConsent && (
          <label className="agentcard-consent">
            <Checkbox checked={accepted} onCheckedChange={(checked) => setAccepted(checked === true)} />
            <span>I have reviewed these items and authorize this exact total for payment through PayPal.</span>
          </label>
        )}

        {error && <p className="agentcard-inline-error" role="alert">{error}</p>}
        {notice && <p className="agentcard-inline-notice" role="status">{notice}</p>}

        {paid ? (
          <section className="agentcard-result agentcard-result-success">
            <h2>Payment successful</h2>
            <p>{formatAmount(checkoutStatus?.amount_minor ?? checkout.total_amount_minor, checkout.currency)} was confirmed by PayPal.</p>
            {checkoutStatus?.receipt_url
              ? <a className="agentcard-receipt-link" href={checkoutStatus.receipt_url} target="_blank" rel="noreferrer">Download receipt</a>
              : <p>Your receipt is being prepared. It will also be sent in your original conversation when available.</p>}
          </section>
        ) : waiting ? (
          <section className="agentcard-result">
            <h2>Payment processing</h2>
            <p>We are checking the payment directly with PayPal. Do not pay again while this status is pending.</p>
          </section>
        ) : unavailable ? (
          <section className="agentcard-result">
            <h2>{stateMessage(state)}</h2>
            <p>Return to your conversation with the business to request an updated checkout. Do not use an expired or cancelled link.</p>
          </section>
        ) : (
          <>
            <Button
              className="agentcard-pay-button"
              size="3"
              onClick={() => void continueToPayment()}
              disabled={busy || (needsConsent && !accepted) || !['awaiting_customer', 'awaiting_payment'].includes(state)}
            >
              {busy ? 'Connecting to PayPal…' : state === 'awaiting_payment' ? 'Continue to PayPal' : 'Continue to secure payment'}
            </Button>
            <p className="agentcard-expiry">
              Checkout expires {new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(checkout.expires_at))}
            </p>
          </>
        )}

        <footer className="agentcard-security-note">
          <ShieldCheck size={16} />
          <span>Reactant never receives or stores your card number or security code.</span>
        </footer>
      </main>
    </CheckoutShell>
  )
}

function CheckoutShell({ children }: { children: React.ReactNode }) {
  return (
    <Theme accentColor="grass" grayColor="slate" radius="large" appearance="light">
      <div className="agentcard-page">{children}</div>
    </Theme>
  )
}
