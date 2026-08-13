import { useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { API_BASE } from '../api';

const COPY = {
  vi: { intro: 'Để lại thông tin để bắt đầu trò chuyện với trợ lý ảo:', name: 'Họ và tên', phone: 'Số điện thoại', consent: 'Tôi đồng ý cho phòng khám lưu thông tin để tư vấn.', start: 'Bắt đầu trò chuyện', welcome: 'Xin chào {name}! Mình là trợ lý ảo của {clinic}. Bạn cần hỗ trợ gì ạ?', connection: 'Xin lỗi, kết nối gặp sự cố. Bạn thử lại giúp nhé.', replying: 'Đang trả lời...', input: 'Nhập tin nhắn...', send: 'Gửi', branch: 'Cơ sở bạn muốn đến', branchAny: '— Để phòng khám tư vấn giúp —', branchFull: 'chưa nhận đặt lịch online' },
  en: { intro: 'Leave your details to start a conversation with our virtual assistant:', name: 'Full name', phone: 'Phone number', consent: 'I consent to the clinic storing my details for consultation.', start: 'Start chat', welcome: 'Hello {name}! I am the virtual assistant for {clinic}. How can I help?', connection: 'Sorry, the connection failed. Please try again.', replying: 'Replying...', input: 'Type a message...', send: 'Send', branch: 'Which location?', branchAny: '— Let the clinic advise me —', branchFull: 'online booking unavailable' },
  ja: { intro: 'バーチャルアシスタントとの会話を始めるために、情報を入力してください。', name: 'お名前', phone: '電話番号', consent: '相談のため、クリニックが私の情報を保存することに同意します。', start: 'チャットを開始', welcome: '{name}様、こんにちは。{clinic}のバーチャルアシスタントです。どのようにお手伝いできますか？', connection: '接続に失敗しました。もう一度お試しください。', replying: '返信中...', input: 'メッセージを入力...', send: '送信', branch: 'ご希望の店舗', branchAny: '— クリニックに相談する —', branchFull: 'オンライン予約不可' },
};

/**
 * Public per-clinic chat page reached via a unique link /c/<slug>.
 * Resolves the slug to a clinic, shows its branding, and runs the AI chat
 * scoped to that clinic (same endpoints the embeddable widget uses).
 */
export default function ClinicChatPage() {
  const { slug, brandSlug, branchSlug, orgSlug, clinicSlug } = useParams();
  // /chat/<brand>[/<branch>] is the current shape. The older /c/<slug> and
  // /book/<org>/<clinic>/chat links are still routed here so previously shared
  // links and printed QR codes keep working.
  const resolveUrl = brandSlug
    ? `${API_BASE}/public/resolve/${brandSlug}${branchSlug ? `/${branchSlug}` : ''}`
    : orgSlug && clinicSlug
      ? `${API_BASE}/public/org/${orgSlug}/clinics/${clinicSlug}`
      : `${API_BASE}/public/clinic-by-slug/${slug}`;
  const [clinic, setClinic] = useState(null);
  const [locale, setLocale] = useState('vi');
  const [sessionToken, setSessionToken] = useState(null);
  const t = (key, values = {}) => (COPY[locale]?.[key] || COPY.en[key] || key).replace(/\{(\w+)\}/g, (_, name) => values[name] || '');
  const [notFound, setNotFound] = useState(false);
  const [lead, setLead] = useState({ full_name: '', phone: '', consent: false });
  // Which location the booking is for. Preselected when the URL named one
  // (/chat/<brand>/<branch>), otherwise the patient chooses before starting.
  const [branchId, setBranchId] = useState('');
  const [convId, setConvId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [err, setErr] = useState('');
  const endRef = useRef(null);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(resolveUrl);
        if (!res.ok) { setNotFound(true); return; }
        const data = await res.json();
        setClinic(data);
        setBranchId(data.branch?.id ? String(data.branch.id) : '');
        setLocale(COPY[data.default_locale] ? data.default_locale : 'vi');
      } catch { setNotFound(true); }
    })();
  }, [resolveUrl]);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  // The clinic's own typefaces, loaded only here. The staff app runs on Inter
  // and has no reason to carry two more families for a page it never renders.
  useEffect(() => {
    const id = 'caredesk-brand-fonts';
    if (document.getElementById(id)) return;
    const link = document.createElement('link');
    link.id = id;
    link.rel = 'stylesheet';
    link.href = 'https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500;600&family=Manrope:wght@300;400;500;600;700&display=swap';
    document.head.appendChild(link);
  }, []);

  const start = async (e) => {
    e.preventDefault();
    setErr('');
    if (!lead.consent) { setErr(locale === 'vi' ? 'Vui lòng đồng ý chính sách bảo mật để bắt đầu.' : locale === 'ja' ? '続行するには同意が必要です。' : 'Please consent to continue.'); return; }
    try {
      const res = await fetch(`${API_BASE}/chat/conversations`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', ...(sessionToken ? { 'X-CareDesk-Session': sessionToken } : {}) },
        body: JSON.stringify({
          full_name: lead.full_name, phone: lead.phone, source: 'web',
          consent_given: true, clinic_id: clinic.clinic_id, locale,
          branch_id: branchId ? Number(branchId) : null,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Unable to start the conversation');
      setConvId(data.id);
      setSessionToken(data.public_session_token || null);
      setMessages([{ sender: 'bot', content: t('welcome', { name: lead.full_name || t('name'), clinic: clinic.name }) }]);
    } catch (e2) { setErr(e2.message); }
  };

  const send = async (e) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || sending) return;
    setInput('');
    setMessages(prev => [...prev, { sender: 'patient', content: text }]);
    setSending(true);
    try {
      const res = await fetch(`${API_BASE}/chat/conversations/${convId}/messages`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', ...(sessionToken ? { 'X-CareDesk-Session': sessionToken } : {}) },
        body: JSON.stringify({ content: text }),
      });
      const data = await res.json();
      setSessionToken(res.headers.get('X-CareDesk-Session') || sessionToken);
      if (data?.content) setMessages(prev => [...prev, { sender: 'bot', content: data.content }]);
    } catch {
      setMessages(prev => [...prev, { sender: 'bot', content: t('connection') }]);
    } finally { setSending(false); }
  };

  if (notFound) return (
    <div style={sx.page}><div style={sx.card}>
      <div style={{ fontSize: 44 }}>🔍</div>
      <h2 style={{ fontFamily: C.serif, fontWeight: 500, color: C.ink }}>Không tìm thấy phòng khám</h2>
      <p style={{ color: C.muted, fontSize: 14 }}>Liên kết này không tồn tại hoặc đã thay đổi.</p>
    </div></div>
  );
  if (!clinic) return <div style={sx.page}><div style={sx.card}>Đang tải...</div></div>;

  return (
    <div style={sx.page}>
      <div style={sx.chatCard}>
        <div style={sx.header}>
          {clinic.logo_url
            ? <img src={clinic.logo_url} alt="" style={sx.logo} />
            : <div style={{ ...sx.logo, ...sx.logoFallback }}>{clinic.name.slice(0, 1)}</div>}
          <div style={{ minWidth: 0 }}>
            <div style={sx.clinicName}>{clinic.name}</div>
            {(() => {
              // Show the location actually being booked, so the patient can see
              // at a glance they landed on the one they clicked.
              const picked = clinic.branches?.find(b => String(b.id) === String(branchId));
              const line = picked
                ? `${picked.name}${picked.address ? ` — ${picked.address}` : ''}`
                : clinic.address;
              return line ? <div style={{ fontSize: 11.5, color: 'rgba(245,241,234,.72)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{line}</div> : null;
            })()}
          </div>
          <select aria-label="Language" value={locale} onChange={(e) => setLocale(e.target.value)}
            style={{ marginLeft: 'auto', flex: 'none', padding: '4px 6px', fontFamily: 'inherit', fontSize: 11.5, fontWeight: 600, letterSpacing: '.06em', color: C.ivory, background: 'transparent', border: '1px solid rgba(245,241,234,.4)' }}>
            <option value="vi" style={{ color: C.ink }}>VI</option>
            <option value="en" style={{ color: C.ink }}>EN</option>
            <option value="ja" style={{ color: C.ink }}>JA</option>
          </select>
        </div>

        {!convId ? (
          <form onSubmit={start} style={sx.consent}>
            <p style={{ color: C.inkSoft, fontSize: 14, margin: '4px 0 8px', lineHeight: 1.6 }}>
              {t('intro')}
            </p>
            <input style={sx.input} placeholder={t('name')} value={lead.full_name}
              onChange={e => setLead({ ...lead, full_name: e.target.value })} required />
            <input style={sx.input} placeholder={t('phone')} value={lead.phone}
              onChange={e => setLead({ ...lead, phone: e.target.value })} required />
            {clinic.branches?.length > 1 && (
              <label style={{ fontSize: 12, color: C.muted, display: 'flex', flexDirection: 'column', gap: 5 }}>
                {t('branch')}
                <select style={sx.input} value={branchId} onChange={e => setBranchId(e.target.value)}>
                  <option value="">{t('branchAny')}</option>
                  {clinic.branches.map(b => (
                    <option key={b.id} value={b.id} disabled={!b.bookable}>
                      {b.name}{b.address ? ` — ${b.address}` : ''}{b.bookable ? '' : ` (${t('branchFull')})`}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label style={{ display: 'flex', gap: 9, alignItems: 'flex-start', fontSize: 13, color: C.inkSoft, lineHeight: 1.5 }}>
              <input type="checkbox" checked={lead.consent}
                onChange={e => setLead({ ...lead, consent: e.target.checked })} />
              {t('consent')}
            </label>
            {err && <div style={sx.err}>{err}</div>}
            <button type="submit" style={sx.btn}>{t('start')}</button>
          </form>
        ) : (
          <>
            <div style={sx.msgs}>
              {messages.map((m, i) => (
                <div key={i} style={{
                  alignSelf: m.sender === 'patient' ? 'flex-end' : 'flex-start',
                  maxWidth: '82%', padding: '10px 14px', fontSize: 14, whiteSpace: 'pre-line', lineHeight: 1.5,
                  // A receptionist who has taken over is marked in gold, so the
                  // patient can tell a person from the assistant at a glance.
                  background: m.sender === 'patient' ? C.olive : m.sender === 'agent' ? '#FBF6EA' : C.paper,
                  color: m.sender === 'patient' ? C.ivory : C.ink,
                  border: m.sender === 'patient' ? 'none'
                    : `1px solid ${m.sender === 'agent' ? C.gold : C.line}`,
                }}>{m.content}</div>
              ))}
              {sending && <div style={{ fontSize: 12.5, color: C.muted, padding: '0 4px' }}>{t('replying')}</div>}
              <div ref={endRef} />
            </div>
            <form onSubmit={send} style={sx.inputBar}>
              <input style={{ ...sx.input, margin: 0, flex: 1 }} placeholder={t('input')} value={input}
                onChange={e => setInput(e.target.value)} />
              <button type="submit" style={{ ...sx.btn, width: 'auto', margin: 0, padding: '0 18px', opacity: (sending || !input.trim()) ? 0.5 : 1 }}
                disabled={sending || !input.trim()}>{t('send')}</button>
            </form>
          </>
        )}
      </div>
      <div style={{ marginTop: 14, fontSize: 11, letterSpacing: '.08em', color: C.muted }}>Được vận hành bởi CareDesk AI</div>
    </div>
  );
}

/**
 * Same palette and type as the public landing pages (see templates/base.html):
 * ivory ground, charcoal text, deep olive as the only strong colour. A patient
 * who clicks through from a clinic's page must not feel handed to a different
 * company halfway through booking — the teal gradient this used to wear read as
 * a generic SaaS chat bolted onto an editorial site.
 */
const C = {
  ivory: '#F5F1EA', paper: '#FFFDF9', ink: '#20201D', inkSoft: '#4A4A44',
  muted: '#8A857B', olive: '#3F493D', oliveLt: '#5C6858', gold: '#B99A5B',
  line: '#E0D9CC',
  serif: '"Cormorant Garamond",Georgia,"Times New Roman",serif',
  sans: '"Manrope",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif',
};

const sx = {
  page: { minHeight: '100vh', background: C.ivory, color: C.ink, fontFamily: C.sans, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: 20 },
  card: { background: C.paper, border: `1px solid ${C.line}`, padding: 40, maxWidth: 420, textAlign: 'center' },
  chatCard: { width: '100%', maxWidth: 440, background: C.ivory, border: `1px solid ${C.line}`, overflow: 'hidden', boxShadow: '0 20px 50px rgba(32,32,29,.14)', display: 'flex', flexDirection: 'column', height: '78vh', maxHeight: 680 },
  header: { display: 'flex', gap: 12, alignItems: 'center', padding: '16px 18px', background: C.olive, color: C.ivory },
  logo: { width: 40, height: 40, borderRadius: '50%', objectFit: 'cover', flex: 'none' },
  logoFallback: { background: 'rgba(245,241,234,.16)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: C.serif, fontSize: 20 },
  clinicName: { fontFamily: C.serif, fontSize: 18, fontWeight: 500, lineHeight: 1.2 },
  consent: { padding: 20, display: 'flex', flexDirection: 'column', gap: 11, overflowY: 'auto' },
  input: { width: '100%', padding: '11px 12px', fontFamily: 'inherit', fontSize: 14, color: C.ink, background: C.paper, border: `1px solid ${C.line}`, borderRadius: 0, boxSizing: 'border-box' },
  btn: { width: '100%', padding: 14, fontFamily: 'inherit', fontSize: 13, fontWeight: 600, letterSpacing: '.06em', textTransform: 'uppercase', color: C.ivory, background: C.olive, border: `1px solid ${C.olive}`, cursor: 'pointer' },
  err: { color: '#9F3A38', fontSize: 13 },
  msgs: { flex: 1, overflowY: 'auto', padding: 16, display: 'flex', flexDirection: 'column', gap: 10 },
  inputBar: { display: 'flex', gap: 8, padding: 12, borderTop: `1px solid ${C.line}`, background: C.paper },
};
