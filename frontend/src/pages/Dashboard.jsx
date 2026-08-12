import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { API_BASE, getAuthHeaders } from '../api';

const fmtMoney = (v) => new Intl.NumberFormat('vi-VN').format(v || 0) + 'đ';

function RevenueCard({ title, value, sub, accent }) {
  return (
    <div className="stat-card" style={accent ? { borderTop: `3px solid ${accent}` } : {}}>
      <div className="stat-info">
        <h3>{title}</h3>
        <div className="stat-number" style={{ fontSize: '22px', color: accent || 'var(--dark-color)' }}>{value}</div>
        {sub && <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>{sub}</div>}
      </div>
    </div>
  );
}

/**
 * One of the two numbers CareDesk is sold on, shown against what the clinic
 * itself reported before signing up. Percentages alone cannot answer "what did
 * I get for my money" — the comparison is the whole point.
 */
function BaselineCard({ title, before, now, unit, higherIsBetter }) {
  const hasBefore = before !== null && before !== undefined;
  const delta = hasBefore ? now - before : null;
  const improved = delta === null ? null : (higherIsBetter ? delta > 0 : delta < 0);
  const colour = improved === null ? 'var(--text-muted)' : improved ? '#0d9488' : '#dc2626';
  const fmt = (v) => (v === null || v === undefined ? '—' : `${v}${unit === '%' ? '%' : ` ${unit}`}`);

  return (
    <div className="stat-card" style={{ borderTop: `3px solid ${colour}` }}>
      <div className="stat-info">
        <h3>{title}</h3>
        <div className="stat-number" style={{ fontSize: '22px', color: colour }}>{fmt(now)}</div>
        <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
          {hasBefore
            ? <>Trước khi dùng CareDesk: {fmt(before)}
                {delta !== null && (
                  <strong style={{ color: colour, marginLeft: 6 }}>
                    {delta > 0 ? '+' : ''}{Math.round(delta * 10) / 10}
                  </strong>
                )}
              </>
            : 'Chưa nhập số liệu ban đầu'}
        </div>
      </div>
    </div>
  );
}

/**
 * Whether patients come back — the number this product ultimately lives or dies
 * on. Deliberately refuses to show a percentage until the cohort is big enough:
 * with three patients one of them swings it by 33 points, and a figure that
 * moves like that will be argued with rather than believed.
 */
function RetentionCard({ r }) {
  const before = r.baseline_percent;
  const delta = r.percent != null && before != null ? r.percent - before : null;
  const good = delta == null ? null : delta > 0;
  const colour = good == null ? '#0f172a' : good ? '#0d9488' : '#dc2626';

  return (
    <div className="card-table-wrapper" style={{ padding: '16px 20px', marginBottom: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', alignItems: 'center' }}>
        <div>
          <h3 style={{ margin: 0, fontSize: 14 }}>⭐ Tỷ lệ khách quay lại</h3>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
            Trong nhóm khách khám lần đầu, bao nhiêu % quay lại trong {r.window_days} ngày
          </div>
        </div>
        <div style={{ textAlign: 'right' }}>
          {r.percent == null || !r.is_reliable ? (
            <>
              <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text-muted)' }}>Chưa đủ dữ liệu</div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                {r.cohort_size} khách trong nhóm — cần thêm thời gian
              </div>
            </>
          ) : (
            <>
              <div style={{ fontSize: 26, fontWeight: 700, color: colour }}>
                {r.percent}%
                {delta != null && (
                  <span style={{ fontSize: 14, marginLeft: 8 }}>
                    {delta > 0 ? '+' : ''}{Math.round(delta * 10) / 10}
                  </span>
                )}
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                {r.returned}/{r.cohort_size} khách
                {before != null && <> · trước khi dùng CareDesk: {before}%</>}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function CopilotBox() {
  const [messages, setMessages] = useState([
    { role: 'bot', text: "Chào bạn! Hỏi tôi: 'Hôm nay có bao nhiêu lịch hẹn?', 'Doanh thu tháng này?', 'Tỷ lệ no-show?'..." }
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const ask = async (e) => {
    e.preventDefault();
    const q = input.trim();
    if (!q || loading) return;
    setInput('');
    setMessages(prev => [...prev, { role: 'user', text: q }]);
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/copilot/ask`, {
        method: 'POST', headers: getAuthHeaders(), body: JSON.stringify({ question: q })
      });
      const data = await res.json();
      setMessages(prev => [...prev, { role: 'bot', text: data.answer || 'Không có dữ liệu.' }]);
    } catch {
      setMessages(prev => [...prev, { role: 'bot', text: 'Lỗi kết nối máy chủ.' }]);
    } finally {
      setLoading(false);
    }
  };

  const suggestions = ['Hôm nay có bao nhiêu lịch hẹn?', 'Doanh thu tháng này?', 'Tình hình gói liệu trình?'];

  return (
    <div className="card-table-wrapper" style={{ display: 'flex', flexDirection: 'column', height: '380px', marginBottom: 0 }}>
      <div className="card-header" style={{ padding: '14px 20px' }}>
        <h2>💬 Hỏi CareDesk Copilot</h2>
      </div>
      <div style={{ flex: 1, overflowY: 'auto', padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: '10px', background: '#f8fafc' }}>
        {messages.map((m, i) => (
          <div key={i} style={{
            alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start',
            maxWidth: '85%', padding: '8px 12px', borderRadius: '12px', fontSize: '12.5px',
            whiteSpace: 'pre-line', lineHeight: 1.45,
            background: m.role === 'user' ? 'var(--primary-color)' : 'white',
            color: m.role === 'user' ? 'white' : 'var(--text-main)',
            border: m.role === 'user' ? 'none' : '1px solid var(--border-color)'
          }}>{m.text}</div>
        ))}
        {loading && <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Đang tra cứu...</div>}
        <div ref={endRef} />
      </div>
      <div style={{ padding: '8px 12px', display: 'flex', gap: '6px', flexWrap: 'wrap', borderTop: '1px solid var(--border-color)' }}>
        {suggestions.map(s => (
          <button key={s} className="btn btn-secondary btn-sm" style={{ fontSize: '10px', padding: '3px 8px' }}
            onClick={() => setInput(s)}>{s}</button>
        ))}
      </div>
      <form onSubmit={ask} style={{ padding: '10px 12px', display: 'flex', gap: '8px', borderTop: '1px solid var(--border-color)' }}>
        <input className="form-control" style={{ fontSize: '13px' }} placeholder="Nhập câu hỏi..."
          value={input} onChange={(e) => setInput(e.target.value)} />
        <button type="submit" className="btn btn-primary btn-sm" disabled={loading || !input.trim()}>Hỏi</button>
      </form>
    </div>
  );
}

export default function Dashboard() {
  const [report, setReport] = useState(null);
  const [isManager, setIsManager] = useState(false);
  const [todayAppointments, setTodayAppointments] = useState([]);
  const [handoffConversations, setHandoffConversations] = useState([]);
  const [stats, setStats] = useState({ appointmentsTodayCount: 0, conversationsCount: 0, pendingAppointmentsCount: 0, handoffCount: 0 });
  const [readiness, setReadiness] = useState(null);
  const [flags, setFlags] = useState({});
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    const fetchAll = async () => {
      const headers = getAuthHeaders();
      try {
        const meRes = await fetch(`${API_BASE}/auth/me`, { headers });
        if (meRes.status === 401) throw new Error('Unauthorized');
        const me = await meRes.json();
        const manager = me.role === 'owner';
        setIsManager(manager);

        // Revenue report (this month) - owners only
        if (manager) {
          const start = new Date();
          start.setDate(1);
          const params = new URLSearchParams({
            start_date: start.toISOString().split('T')[0],
            end_date: new Date().toISOString().split('T')[0]
          });
          const repRes = await fetch(`${API_BASE}/reports/summary?${params}`, { headers });
          if (repRes.ok) setReport(await repRes.json());
        }

        // What is stopping this clinic from operating (missing schedule, no
        // message channel). Fetched for every role: a receptionist is usually
        // the first to notice reminders are not going out.
        const readyRes = await fetch(`${API_BASE}/clinic/readiness`, { headers });
        if (readyRes.ok) setReadiness(await readyRes.json());

        const featRes = await fetch(`${API_BASE}/clinic/features`, { headers });
        if (featRes.ok) setFlags((await featRes.json()).flags || {});

        // Operational data
        const [apptsRes, convsRes] = await Promise.all([
          fetch(`${API_BASE}/appointments`, { headers }),
          fetch(`${API_BASE}/chat/conversations`, { headers })
        ]);
        const appts = await apptsRes.json();
        const convs = await convsRes.json();
        const todayStr = new Date().toISOString().split('T')[0];
        const apptsToday = appts.filter(a => a.start_time.startsWith(todayStr));
        const handoffs = convs.filter(c => c.status === 'handoff_requested');
        setStats({
          appointmentsTodayCount: apptsToday.length,
          conversationsCount: convs.length,
          pendingAppointmentsCount: appts.filter(a => a.status === 'pending' || a.status === 'awaiting_deposit').length,
          handoffCount: handoffs.length
        });
        setTodayAppointments(apptsToday.slice(0, 5));
        setHandoffConversations(handoffs);
      } catch (err) {
        console.error(err);
        if (err.message === 'Unauthorized') {
          localStorage.removeItem('caredesk_token');
          navigate('/login');
        }
      } finally {
        setLoading(false);
      }
    };
    fetchAll();
  }, [navigate]);

  if (loading) return <div style={{ padding: '24px', textAlign: 'center' }}>Đang tải dữ liệu...</div>;

  const t = report?.totals;

  return (
    <div>
      <div className="page-header">
        <div className="page-title">
          <h1>Cỗ máy doanh thu của phòng khám</h1>
          <p>{isManager ? 'Số liệu tháng này — AI đang kiếm tiền cho bạn thế nào.' : 'Tình hình vận hành hôm nay.'}</p>
        </div>
      </div>

      {/* Blockers first. A clinic whose reminders are going nowhere needs to
          know that before it reads any revenue number. */}
      {readiness?.blockers?.filter(b => b.severity === 'critical').map(b => (
        <div key={b.code} onClick={() => navigate(b.action)} style={{
          background: '#fef2f2', border: '1px solid #fecaca', borderLeft: '4px solid #dc2626',
          borderRadius: 8, padding: '12px 16px', marginBottom: 10, cursor: 'pointer',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12,
        }}>
          <span style={{ color: '#991b1b', fontSize: 14 }}>⚠️ {b.message}</span>
          <span style={{ color: '#dc2626', fontSize: 13, fontWeight: 600, whiteSpace: 'nowrap' }}>Sửa ngay →</span>
        </div>
      ))}

      {/* The two numbers the product is sold on, against what the clinic
          reported before signing up. */}
      {isManager && report?.baseline && (
        <div className="stats-grid" style={{ marginBottom: 4 }}>
          <BaselineCard
            title="Lịch hẹn / tháng"
            before={report.baseline.monthly_bookings_before}
            now={report.baseline.monthly_bookings_now}
            unit="lịch" higherIsBetter
          />
          <BaselineCard
            title="Tỷ lệ khách không đến"
            before={report.baseline.no_show_percent_before}
            now={report.baseline.no_show_percent_now}
            unit="%" higherIsBetter={false}
          />
        </div>
      )}

      {/* The North Star. Shown separately from the two sales numbers because it
          is the slow one: the cohort needs ~3 months before it says anything,
          and pretending otherwise invites an argument at the review. */}
      {isManager && report?.retention && <RetentionCard r={report.retention} />}

      {/* Revenue hero cards (owner only) */}
      {isManager && t && (
        <div className="stats-grid">
          <RevenueCard
            title="Doanh thu AI tạo ra" accent="var(--primary-color)"
            value={fmtMoney(t.ai_revenue)}
            sub={`Tổng ghi nhận: ${fmtMoney(t.ledger_revenue)} · Bán gói: ${fmtMoney((report.revenue_by_source || {}).package || 0)}`}
          />
          <RevenueCard
            title="Lịch AI tự chốt" accent="#3b82f6"
            value={t.ai_booked_appointments}
            sub={`Chuyển đổi hội thoại → lịch: ${report.conversion_rate_percent}%`}
          />
          <RevenueCard
            title="ROI trên phí CareDesk" accent="#10b981"
            value={t.roi != null ? `${t.roi}x` : '—'}
            sub={t.monthly_fee > 0 ? `Phí gói: ${fmtMoney(t.monthly_fee)}/tháng` : 'Chưa cấu hình phí gói'}
          />
          <RevenueCard
            title="No-show" accent="#f59e0b"
            value={`${report.no_show_rate_percent}%`}
            sub={`Khách quay lại (2+ lần): ${t.returning_patients} · Gói chưa dùng: ${fmtMoney(t.unused_package_value)}`}
          />
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '24px' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          {/* Operational stats row */}
          <div className="stats-grid" style={{ marginBottom: 0 }}>
            <div className="stat-card">
              <div className="stat-info"><h3>Lịch hẹn hôm nay</h3><div className="stat-number">{stats.appointmentsTodayCount}</div></div>
            </div>
            <div className="stat-card">
              <div className="stat-info"><h3>Chờ xác nhận</h3><div className="stat-number">{stats.pendingAppointmentsCount}</div></div>
            </div>
            <div className="stat-card" style={stats.handoffCount > 0 ? { border: '1.5px solid var(--danger-color)', backgroundColor: '#fff5f5' } : {}}>
              <div className="stat-info">
                <h3 style={stats.handoffCount > 0 ? { color: 'var(--danger-color)' } : {}}>Cần người thật</h3>
                <div className="stat-number" style={stats.handoffCount > 0 ? { color: 'var(--danger-color)' } : {}}>{stats.handoffCount}</div>
              </div>
            </div>
          </div>

          {/* Today's appointments */}
          <div className="card-table-wrapper" style={{ marginBottom: 0 }}>
            <div className="card-header">
              <h2>Lịch hẹn hôm nay</h2>
              <Link to="/appointments" className="btn btn-secondary btn-sm">Xem tất cả</Link>
            </div>
            {todayAppointments.length === 0 ? (
              <div style={{ padding: '28px', textAlign: 'center', color: 'var(--text-muted)' }}>Chưa có lịch hẹn nào hôm nay.</div>
            ) : (
              <table className="custom-table">
                <thead>
                  <tr><th>Khách hàng</th><th>Dịch vụ</th><th>Giờ</th><th>Nguồn</th><th>Trạng thái</th></tr>
                </thead>
                <tbody>
                  {todayAppointments.map((appt) => (
                    <tr key={appt.id}>
                      <td>
                        <div style={{ fontWeight: 600 }}>{appt.patient?.full_name}</div>
                        <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{appt.patient?.phone}</div>
                      </td>
                      <td>{appt.service?.name}</td>
                      <td>{new Date(appt.start_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</td>
                      <td>
                        {(appt.booking_source || '').startsWith('ai') ? (
                          <span className="badge completed" style={{ fontSize: '10px' }}>🤖 AI chốt</span>
                        ) : (
                          <span className="badge no_show" style={{ fontSize: '10px' }}>Lễ tân</span>
                        )}
                      </td>
                      <td><span className={`badge ${appt.status}`}>{appt.status}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {/* Handoff panel */}
          {handoffConversations.length > 0 && (
            <div className="card-table-wrapper" style={{ marginBottom: 0 }}>
              <div className="card-header" style={{ backgroundColor: '#fffbeb' }}>
                <h2 style={{ color: '#b45309' }}>⚠️ Hội thoại cần người thật ({handoffConversations.length})</h2>
                <Link to="/inbox" className="btn btn-primary btn-sm">Mở Inbox</Link>
              </div>
              <div style={{ padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {handoffConversations.slice(0, 4).map((conv) => (
                  <div key={conv.id} style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 12px', border: '1px solid #fde68a', borderRadius: '8px', background: '#fffdf5' }}>
                    <span style={{ fontWeight: 600, fontSize: '13px' }}>{conv.patient?.full_name}</span>
                    <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{conv.patient?.phone}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Copilot */}
        {flags.copilot && <CopilotBox />}
      </div>
    </div>
  );
}
