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
      <h2 style={{ color: '#0f172a' }}>Không tìm thấy phòng khám</h2>
      <p style={{ color: '#64748b' }}>Liên kết này không tồn tại hoặc đã thay đổi.</p>
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
          <div>
            <div style={{ fontWeight: 700, fontSize: 16 }}>{clinic.name}</div>
            {(() => {
              // Show the location actually being booked, so the patient can see
              // at a glance they landed on the one they clicked.
              const picked = clinic.branches?.find(b => String(b.id) === String(branchId));
              const line = picked
                ? `${picked.name}${picked.address ? ` — ${picked.address}` : ''}`
                : clinic.address;
              return line ? <div style={{ fontSize: 12, opacity: 0.85 }}>{line}</div> : null;
            })()}
          </div>
          <select aria-label="Language" value={locale} onChange={(e) => setLocale(e.target.value)} style={{ marginLeft: 'auto' }}><option value="vi">VI</option><option value="en">EN</option><option value="ja">JA</option></select>
        </div>

        {!convId ? (
          <form onSubmit={start} style={sx.consent}>
            <p style={{ color: '#475569', fontSize: 14, margin: '4px 0 8px' }}>
              {t('intro')}
            </p>
            <input style={sx.input} placeholder={t('name')} value={lead.full_name}
              onChange={e => setLead({ ...lead, full_name: e.target.value })} required />
            <input style={sx.input} placeholder={t('phone')} value={lead.phone}
              onChange={e => setLead({ ...lead, phone: e.target.value })} required />
            {clinic.branches?.length > 1 && (
              <label style={{ fontSize: 12, color: '#64748b', display: 'flex', flexDirection: 'column', gap: 4 }}>
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
            <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13, color: '#475569' }}>
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
                  maxWidth: '82%', padding: '9px 13px', borderRadius: 14, fontSize: 14, whiteSpace: 'pre-line', lineHeight: 1.45,
                  background: m.sender === 'patient' ? '#0d9488' : '#fff',
                  color: m.sender === 'patient' ? '#fff' : '#334155',
                  border: m.sender === 'patient' ? 'none' : '1px solid #e2e8f0',
                }}>{m.content}</div>
              ))}
              {sending && <div style={{ fontSize: 12, color: '#94a3b8' }}>{t('replying')}</div>}
              <div ref={endRef} />
            </div>
            <form onSubmit={send} style={sx.inputBar}>
              <input style={{ ...sx.input, margin: 0, flex: 1 }} placeholder={t('input')} value={input}
                onChange={e => setInput(e.target.value)} />
              <button type="submit" style={{ ...sx.btn, width: 'auto', margin: 0, padding: '10px 18px' }}
                disabled={sending || !input.trim()}>{t('send')}</button>
            </form>
          </>
        )}
      </div>
      <div style={{ marginTop: 12, fontSize: 11, color: '#94a3b8' }}>Được vận hành bởi CareDesk AI</div>
    </div>
  );
}

const sx = {
  page: { minHeight: '100vh', background: 'linear-gradient(135deg,#0f172a,#115e59)', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: 20 },
  card: { background: '#fff', borderRadius: 16, padding: 40, maxWidth: 420, textAlign: 'center', boxShadow: '0 10px 30px rgba(0,0,0,.2)' },
  chatCard: { width: '100%', maxWidth: 440, background: '#f8fafc', borderRadius: 16, overflow: 'hidden', boxShadow: '0 10px 40px rgba(0,0,0,.25)', display: 'flex', flexDirection: 'column', height: '78vh', maxHeight: 680 },
  header: { display: 'flex', gap: 12, alignItems: 'center', padding: '16px 18px', background: '#0d9488', color: '#fff' },
  logo: { width: 42, height: 42, borderRadius: 10, objectFit: 'cover' },
  logoFallback: { background: 'rgba(255,255,255,.2)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700, fontSize: 20 },
  consent: { padding: 20, display: 'flex', flexDirection: 'column', gap: 10 },
  input: { width: '100%', padding: '10px 12px', fontSize: 14, border: '1px solid #cbd5e1', borderRadius: 8, boxSizing: 'border-box' },
  btn: { width: '100%', padding: 12, fontSize: 14, fontWeight: 600, color: '#fff', background: 'linear-gradient(135deg,#14b8a6,#0f766e)', border: 'none', borderRadius: 8, cursor: 'pointer' },
  err: { color: '#dc2626', fontSize: 13 },
  msgs: { flex: 1, overflowY: 'auto', padding: 14, display: 'flex', flexDirection: 'column', gap: 9 },
  inputBar: { display: 'flex', gap: 8, padding: 12, borderTop: '1px solid #e2e8f0', background: '#fff' },
};
