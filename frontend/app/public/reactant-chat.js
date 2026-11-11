(() => {
  const script = document.currentScript
  const businessId = script?.dataset.businessId
  const apiBase = (script?.dataset.apiUrl || 'https://reactant.onrender.com/api/v1').replace(/\/$/, '')
  if (!businessId || document.querySelector(`[data-reactant-chat="${businessId}"]`)) return

  const style = document.createElement('style')
  style.textContent = `
    .reactant-chat-root{position:fixed;right:24px;bottom:24px;z-index:2147483000;font:14px/1.45 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#202b23}
    .reactant-chat-launch{width:58px;height:58px;border:0;border-radius:50%;background:#315c3e;color:white;box-shadow:0 8px 26px #162b1c33;font-size:25px;cursor:pointer}
    .reactant-chat-panel{display:none;position:absolute;right:0;bottom:72px;width:min(370px,calc(100vw - 32px));height:min(560px,calc(100vh - 120px));overflow:hidden;border:1px solid #dfe7df;border-radius:18px;background:#fff;box-shadow:0 20px 70px #162b1c2b}
    .reactant-chat-panel[data-open="true"]{display:grid;grid-template-rows:auto 1fr auto}
    .reactant-chat-head{display:flex;align-items:center;justify-content:space-between;padding:15px 17px;background:#f5f8f4;border-bottom:1px solid #e8eee8}
    .reactant-chat-head strong{font-size:15px}.reactant-chat-close{border:0;background:transparent;color:#536157;font-size:22px;cursor:pointer}
    .reactant-chat-messages{overflow:auto;padding:16px;display:flex;flex-direction:column;gap:12px}
    .reactant-chat-bubble{max-width:85%;align-self:flex-start;padding:10px 12px;border-radius:13px;background:#f0f3f0;white-space:pre-wrap;overflow-wrap:anywhere}
    .reactant-chat-bubble[data-sender="customer"]{align-self:flex-end;background:#e6f0e7}
    .reactant-chat-bubble img{display:block;width:100%;max-height:210px;margin-top:8px;object-fit:contain;border-radius:8px}
    .reactant-chat-compose{display:grid;gap:8px;padding:12px;border-top:1px solid #e8eee8}
    .reactant-chat-consent{display:flex;align-items:flex-start;gap:7px;color:#66736a;font-size:11px}
    .reactant-chat-input-row{display:flex;gap:8px}
    .reactant-chat-input{flex:1;min-width:0;padding:10px 12px;border:1px solid #dfe7df;border-radius:11px;font:inherit;outline:none}
    .reactant-chat-input:focus{border-color:#6c9275;box-shadow:0 0 0 3px #315c3e18}
    .reactant-chat-attach{display:grid;place-items:center;width:40px;border:1px solid #dfe7df;border-radius:10px;color:#536157;cursor:pointer}
    .reactant-chat-attach input{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}
    .reactant-chat-send{border:0;border-radius:10px;padding:0 14px;background:#315c3e;color:#fff;font:inherit;font-weight:600;cursor:pointer}
    .reactant-chat-launch:focus-visible,.reactant-chat-close:focus-visible,.reactant-chat-attach:focus-within,.reactant-chat-send:focus-visible{outline:3px solid #91b79a;outline-offset:2px}
    .reactant-chat-send:disabled{opacity:.55;cursor:wait}.reactant-chat-note{color:#69766c;font-size:12px}
    @media(max-width:520px){.reactant-chat-root{right:12px;bottom:12px}.reactant-chat-panel{position:fixed;inset:auto 8px 82px;width:auto;height:min(70dvh,600px)}}
  `
  document.head.append(style)

  const root = document.createElement('div')
  root.className = 'reactant-chat-root'
  root.dataset.reactantChat = businessId
  root.innerHTML = `
    <section class="reactant-chat-panel" aria-label="Chat with the business" data-open="false">
      <header class="reactant-chat-head"><strong>Chat with us</strong><button class="reactant-chat-close" type="button" aria-label="Close chat">×</button></header>
      <div class="reactant-chat-messages" aria-live="polite"></div>
      <form class="reactant-chat-compose">
        <label class="reactant-chat-consent"><input type="checkbox" name="memory-consent"> Let the agent remember my preferences for future chats.</label>
        <div class="reactant-chat-input-row">
          <label class="reactant-chat-attach" aria-label="Attach product or other image">＋<input class="reactant-chat-file" type="file" accept="image/jpeg,image/png,image/webp" multiple></label>
          <input class="reactant-chat-input" maxlength="4000" placeholder="Write a message..." aria-label="Write a message">
          <button class="reactant-chat-send" type="submit">Send</button>
        </div>
        <small class="reactant-chat-note"></small>
      </form>
    </section>
    <button class="reactant-chat-launch" type="button" aria-label="Open chat">✦</button>
  `
  document.body.append(root)

  const panel = root.querySelector('.reactant-chat-panel')
  const messages = root.querySelector('.reactant-chat-messages')
  const form = root.querySelector('.reactant-chat-compose')
  const input = root.querySelector('.reactant-chat-input')
  const fileInput = root.querySelector('.reactant-chat-file')
  const note = root.querySelector('.reactant-chat-note')
  const memoryConsent = root.querySelector('[name="memory-consent"]')
  const messageElements = new Map()
  const visitorStorageKey = `reactant.widget.visitor.${businessId}`
  const consentStorageKey = `reactant.widget.memory-consent.${businessId}`
  memoryConsent.checked = localStorage.getItem(consentStorageKey) === 'true'
  let visitorId = localStorage.getItem(visitorStorageKey)
  if (!visitorId) {
    visitorId = crypto.randomUUID()
    localStorage.setItem(visitorStorageKey, visitorId)
  }
  let sessionToken = ''
  let socket
  let socketGeneration = 0
  let started = false
  let opening = false

  function addMessage(message) {
    if (!message?.id) return
    const existing = messageElements.get(message.id)
    if (existing) {
      appendAttachments(existing, message.attachments)
      return
    }
    const bubble = document.createElement('div')
    bubble.className = 'reactant-chat-bubble'
    bubble.dataset.sender = message.sender_type
    bubble.dataset.messageId = message.id
    bubble.textContent = message.text
    appendAttachments(bubble, message.attachments)
    messages.append(bubble)
    messageElements.set(message.id, bubble)
    messages.scrollTop = messages.scrollHeight
  }

  function appendAttachments(bubble, attachments) {
    const availableImages = [...bubble.querySelectorAll('img')]
    let replacedLocalImage = false
    for (const attachment of attachments || []) {
      if (attachment.type !== 'image' || !attachment.url) continue
      if ([...bubble.querySelectorAll('img')].some((image) => image.src === attachment.url)) continue
      const localImage = availableImages.find((image) => image.src.startsWith('data:image/'))
      if (localImage && !replacedLocalImage) {
        localImage.src = attachment.url
        localImage.alt = attachment.alt || 'Attached image'
        replacedLocalImage = true
        continue
      }
      const image = document.createElement('img')
      image.src = attachment.url
      image.alt = attachment.alt || 'Product image'
      image.loading = 'lazy'
      bubble.append(image)
    }
  }

  async function request(path, options = {}) {
    const headers = { ...(options.headers || {}) }
    if (sessionToken) headers.Authorization = `Bearer ${sessionToken}`
    if (options.body) headers['Content-Type'] = 'application/json'
    const response = await fetch(`${apiBase}${path}`, { ...options, headers })
    const data = await response.json().catch(() => null)
    if (!response.ok) throw new Error(data?.error?.message || 'Chat is temporarily unavailable.')
    return data
  }

  async function connectSocket() {
    if (!sessionToken) return
    const generation = ++socketGeneration
    if (socket && socket.readyState < WebSocket.CLOSING) socket.close(1000)
    const socketUrl = `${apiBase.replace(/^http/, 'ws')}/public/widgets/ws`
    socket = new WebSocket(socketUrl, `reactant-widget.${sessionToken}`)
    socket.onmessage = (event) => {
      try { addMessage(JSON.parse(event.data)) } catch { /* Invalid frames are ignored. */ }
    }
    socket.onclose = (event) => {
      if (generation !== socketGeneration || panel.dataset.open !== 'true' || !sessionToken) return
      if (event.code === 4401) {
        started = false
        void openSession()
      } else if (event.code === 1006 || event.code === 1011) {
        window.setTimeout(connectSocket, 2000)
      }
    }
  }

  async function openSession() {
    if (opening) return
    opening = true
    note.textContent = 'Connecting...'
    try {
      const session = await request(`/public/widgets/${businessId}/sessions`, {
        method: 'POST',
        body: JSON.stringify({
          visitor_id: visitorId,
          memory_consent: memoryConsent.checked,
        }),
      })
      sessionToken = session.session_token
      const config = await request(`/public/widgets/${businessId}/config`)
      root.querySelector('.reactant-chat-head strong').textContent = config.business_name
      const history = await request('/public/widgets/sessions/messages')
      history.forEach(addMessage)
      if (!started && history.length === 0) {
        addMessage({ id: `greeting-${businessId}`, sender_type: 'agent', text: config.greeting, attachments: [] })
      }
      started = true
      connectSocket()
      note.textContent = ''
    } catch (error) {
      note.textContent = error instanceof Error ? error.message : 'Chat is temporarily unavailable.'
    } finally {
      opening = false
    }
  }

  root.querySelector('.reactant-chat-launch').addEventListener('click', () => {
    panel.dataset.open = 'true'
    if (!started) void openSession()
    input.focus()
  })
  root.querySelector('.reactant-chat-close').addEventListener('click', () => { panel.dataset.open = 'false' })
  fileInput.addEventListener('change', () => {
    const files = [...fileInput.files]
    const supported = files.every((file) => ['image/jpeg', 'image/png', 'image/webp'].includes(file.type))
    const totalBytes = files.reduce((total, file) => total + file.size, 0)
    if (files.length > 3 || !supported || totalBytes > 5 * 1024 * 1024) {
      note.textContent = 'Choose up to 3 JPEG, PNG, or WebP images (5 MB total).'
      fileInput.value = ''
      return
    }
    note.textContent = files.length ? `${files.length} image${files.length === 1 ? '' : 's'} ready to send.` : ''
  })
  memoryConsent.addEventListener('change', () => {
    localStorage.setItem(consentStorageKey, String(memoryConsent.checked))
    if (started) {
      if (socket && socket.readyState < WebSocket.CLOSING) socket.close(1000)
      messageElements.clear()
      messages.replaceChildren()
      void openSession()
    }
  })
  form.addEventListener('submit', async (event) => {
    event.preventDefault()
    const text = input.value.trim()
    const files = [...fileInput.files]
    if ((!text && files.length === 0) || !sessionToken) return
    const button = form.querySelector('.reactant-chat-send')
    button.disabled = true
    let localId = ''
    try {
      const images = await Promise.all(files.map((file) => new Promise((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => resolve(reader.result || '')
        reader.onerror = () => reject(new Error('The selected image could not be read.'))
        reader.readAsDataURL(file)
      })))
      localId = `local-${crypto.randomUUID()}`
      const localAttachments = images.map((url, index) => ({
        type: 'image',
        url,
        alt: files[index].name || 'Attached image',
      }))
      addMessage({ id: localId, sender_type: 'customer', text, attachments: localAttachments })
      const accepted = await request('/public/widgets/sessions/messages', {
        method: 'POST',
        body: JSON.stringify({ text, images }),
      })
      if (accepted?.message_id) {
        const existing = messageElements.get(accepted.message_id)
        const localBubble = messageElements.get(localId)
        if (existing && localBubble && existing !== localBubble) {
          localBubble.remove()
          messageElements.delete(localId)
        } else if (localBubble) {
          messageElements.delete(localId)
          messageElements.set(accepted.message_id, localBubble)
          localBubble.dataset.messageId = accepted.message_id
        }
      }
      input.value = ''
      fileInput.value = ''
      note.textContent = ''
    } catch (error) {
      if (localId) {
        messageElements.get(localId)?.remove()
        messageElements.delete(localId)
      }
      note.textContent = error instanceof Error ? error.message : 'Your message could not be sent.'
    } finally {
      button.disabled = false
      input.focus()
    }
  })
})()
