import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { API_BASE, getAuthHeaders } from '../api';

/**
 * The 15 minutes between signing up and seeing the AI answer with your own
 * prices. Without this a new clinic lands on an empty dashboard and has to find
 * five separate screens before it can try a single chat — which is where most
 * of them stop.
 *
 * Progress is computed by the backend from real data, not from a stored step
 * counter, so filling something in from another screen counts here too.
 */
export default function OnboardingPage() {
  const navigate = useNavigate();
  const [status, setStatus] = useState(null);
  const [baseline, setBaseline] = useState({
    monthly_bookings: '', no_show_percent: '', daily_price_asks: '',
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState(null);

  const load = async () => {
    try {
      const res = await fetch(`${API_BASE}/onboarding/status`, { headers: getAuthHeaders() });
      if (!res.ok) throw new Error();
      setStatus(await res.json());
    } catch {
      setError('Không tải được trạng thái thiết lập.');
    }
  };

  useEffect(() => { load(); }, []);

  const saveBaseline = async () => {
    setSaving(true);
    setError('');
    try {
      const body = {};
      for (const [k, v] of Object.entries(baseline)) {
        if (v !== '') body[k] = Number(v);
      }
      const res = await fetch(`${API_BASE}/onboarding/baseline`, {
        method: 'PUT', headers: getAuthHeaders(), body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error();
      await load();
    } catch {
      setError('Không lưu được số liệu.');
    } finally {
      setSaving(false);
    }
  };

  const goLive = async () => {
    setSaving(true);
    setError('');
    try {
      const res = await fetch(`${API_BASE}/onboarding/complete`, {
        method: 'POST', headers: getAuthHeaders(),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Chưa hoàn tất được.');
      setDone(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  if (!status) {
    return <div style={{ padding: 40 }}>{error || 'Đang tải…'}</div>;
  }

  const blocking = status.steps.filter((s) => s.key !== 'baseline');
  const doneCount = blocking.filter((s) => s.done).length;

  // The payoff screen: the clinic sees its own public link and, more
  // importantly, gets to talk to the AI using the data it just typed in.
  if (done) {
    return (
      <div style={wrap}>
        <h1 style={{ marginBottom: 8 }}>Xong rồi 🎉</h1>
        <p style={{ color: '#475569', marginBottom: 24 }}>
          Trang đặt lịch của phòng khám đã mở. Hãy thử trò chuyện với trợ lý AI
          bằng đúng dữ liệu bạn vừa nhập — hỏi giá một dịch vụ xem sao.
        </p>
        <div style={card}>
          <div style={{ fontSize: 13, color: '#64748b', marginBottom: 6 }}>Link công khai</div>
          <a href={`/book/${done.slug}`} target="_blank" rel="noreferrer"
             style={{ fontSize: 16, fontWeight: 600, wordBreak: 'break-all' }}>
            {window.location.origin}/book/{done.slug}
          </a>
        </div>
        <div style={{ display: 'flex', gap: 12, marginTop: 24, flexWrap: 'wrap' }}>
          <a href={`/chat/${done.slug}`} target="_blank" rel="noreferrer" style={primaryBtn}>
            Chat thử với trợ lý AI
          </a>
          <button onClick={() => navigate('/')} style={ghostBtn}>Vào Dashboard</button>
        </div>
      </div>
    );
  }

  return (
    <div style={wrap}>
      <h1 style={{ marginBottom: 4 }}>Thiết lập phòng khám</h1>
      <p style={{ color: '#475569', marginBottom: 20 }}>
        Khoảng 15 phút. Xong bước 4 là trợ lý AI có thể chốt lịch thật.
      </p>

      <div style={{ height: 6, background: '#e2e8f0', borderRadius: 3, marginBottom: 28 }}>
        <div style={{
          height: '100%', borderRadius: 3, background: '#0d9488',
          width: `${(doneCount / blocking.length) * 100}%`, transition: 'width .3s',
        }} />
      </div>

      {status.steps.map((step, i) => (
        <div key={step.key} style={{ ...card, display: 'flex', alignItems: 'flex-start', gap: 14 }}>
          <div style={{
            width: 28, height: 28, borderRadius: 14, flexShrink: 0,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: step.done ? '#0d9488' : '#e2e8f0',
            color: step.done ? '#fff' : '#64748b', fontWeight: 700, fontSize: 14,
          }}>
            {step.done ? '✓' : i + 1}
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 600 }}>{step.title}</div>
            <div style={{ fontSize: 13, color: '#64748b', marginTop: 2 }}>{step.hint}</div>

            {step.key === 'baseline' && !step.done && (
              <div style={{ marginTop: 12 }}>
                <p style={{ fontSize: 13, color: '#475569', marginBottom: 10 }}>
                  Con số ước chừng là được — quan trọng là có mốc để 2 tháng nữa
                  so sánh xem CareDesk thay đổi được gì.
                </p>
                {[
                  ['monthly_bookings', 'Trung bình mỗi tháng nhận bao nhiêu lịch hẹn?', 'vd. 120'],
                  ['no_show_percent', 'Khoảng bao nhiêu % khách đặt rồi không đến?', 'vd. 25'],
                  ['daily_price_asks', 'Mỗi ngày khoảng bao nhiêu người nhắn hỏi giá?', 'vd. 15'],
                ].map(([key, label, ph]) => (
                  <label key={key} style={{ display: 'block', marginBottom: 10 }}>
                    <span style={{ fontSize: 13, display: 'block', marginBottom: 4 }}>{label}</span>
                    <input
                      type="number" min="0" placeholder={ph} value={baseline[key]}
                      onChange={(e) => setBaseline({ ...baseline, [key]: e.target.value })}
                      style={input}
                    />
                  </label>
                ))}
                <button onClick={saveBaseline} disabled={saving} style={ghostBtn}>
                  {saving ? 'Đang lưu…' : 'Lưu số liệu'}
                </button>
              </div>
            )}
          </div>

          {step.key !== 'baseline' && !step.done && (
            <button onClick={() => navigate(step.path)} style={ghostBtn}>Điền ngay</button>
          )}
        </div>
      ))}

      {error && <div style={{ color: '#b91c1c', marginTop: 16 }}>{error}</div>}

      <div style={{ marginTop: 28 }}>
        <button onClick={goLive} disabled={!status.can_go_live || saving}
                style={{ ...primaryBtn, opacity: status.can_go_live ? 1 : 0.45,
                         cursor: status.can_go_live ? 'pointer' : 'not-allowed' }}>
          {saving ? 'Đang mở…' : 'Mở link công khai & chat thử'}
        </button>
        {!status.can_go_live && (
          <p style={{ fontSize: 13, color: '#64748b', marginTop: 10 }}>
            Còn thiếu bước bắt buộc phía trên. Mở trang đặt lịch khi chưa có lịch
            làm việc thì khách vào sẽ bị trả lời “hiện chưa có khung giờ trống”.
          </p>
        )}
      </div>
    </div>
  );
}

const wrap = { maxWidth: 680, margin: '0 auto', padding: '40px 20px' };
const card = {
  background: '#fff', border: '1px solid #e2e8f0', borderRadius: 10,
  padding: 16, marginBottom: 12,
};
const input = {
  width: '100%', maxWidth: 220, padding: '8px 10px',
  border: '1px solid #cbd5e1', borderRadius: 6, fontSize: 14,
};
const primaryBtn = {
  background: '#0d9488', color: '#fff', border: 'none', borderRadius: 8,
  padding: '11px 20px', fontSize: 15, fontWeight: 600, cursor: 'pointer',
  textDecoration: 'none', display: 'inline-block',
};
const ghostBtn = {
  background: '#fff', color: '#0f172a', border: '1px solid #cbd5e1',
  borderRadius: 8, padding: '9px 16px', fontSize: 14, cursor: 'pointer',
};
