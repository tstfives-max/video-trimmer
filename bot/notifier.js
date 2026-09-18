/**
 * Tiny WeChat notifier for TRIM.
 *
 * Logs into WeChat with wechaty and exposes one HTTP endpoint,
 * POST /notify { message }, which the FastAPI backend calls after a
 * trim job finishes. The message is sent to the WeChat contact/room
 * named in WECHAT_NOTIFY_TARGET.
 *
 * Run: WECHAT_NOTIFY_TARGET="Your Name" node notifier.js
 * (scan the printed QR code once to log the bot in)
 */

const http = require('http')
const { WechatyBuilder } = require('wechaty')

const PORT = process.env.NOTIFIER_PORT || 8788
const NOTIFY_TARGET = process.env.WECHAT_NOTIFY_TARGET

if (!NOTIFY_TARGET) {
  console.error('Set WECHAT_NOTIFY_TARGET to the WeChat contact or room name to notify.')
  process.exit(1)
}

const bot = WechatyBuilder.build({ name: 'trim-notifier' })

bot.on('scan', (qrcode, status) => {
  console.log(`Scan this QR code to log the bot in (status ${status}).`)
  console.log(`Paste this into any QR code generator/viewer:\n${qrcode}`)
  console.log(`Or open: https://wechaty.js.org/qrcode/${encodeURIComponent(qrcode)}`)
})

bot.on('login', (user) => {
  console.log(`Notifier bot logged in as ${user}`)
})

async function sendNotification(message) {
  const contact = await bot.Contact.find({ name: NOTIFY_TARGET })
  if (contact) {
    await contact.say(message)
    return
  }
  const room = await bot.Room.find({ topic: NOTIFY_TARGET })
  if (room) {
    await room.say(message)
    return
  }
  throw new Error(`No WeChat contact or room named "${NOTIFY_TARGET}" found`)
}

const server = http.createServer((req, res) => {
  if (req.method !== 'POST' || req.url !== '/notify') {
    res.writeHead(404).end()
    return
  }

  let body = ''
  req.on('data', (chunk) => { body += chunk })
  req.on('end', async () => {
    try {
      const { message } = JSON.parse(body || '{}')
      if (!message) throw new Error('"message" is required')
      await sendNotification(message)
      res.writeHead(200, { 'Content-Type': 'application/json' })
      res.end(JSON.stringify({ sent: true }))
    } catch (err) {
      res.writeHead(400, { 'Content-Type': 'application/json' })
      res.end(JSON.stringify({ sent: false, error: err.message }))
    }
  })
})

bot.start()
  .then(() => {
    server.listen(PORT, () => {
      console.log(`Notifier HTTP server listening on http://localhost:${PORT}`)
    })
  })
  .catch((err) => {
    console.error('Failed to start WeChat bot:', err)
    process.exit(1)
  })
