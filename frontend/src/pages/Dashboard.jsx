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

const fmtShort = (v) => {
  if (!v) return '0';
  if (v >= 1e9) return (v / 1e9).toFixed(1).replace(/\.0$/, '') + ' tỷ';
  if (v >= 1e6) return (v / 1e6).toFixed(1).replace(/\.0$/, '') + 'tr';
  if (v >= 1e3) return Math.round(v / 1e3) + 'k';
  return String(Math.round(v));
};

/**
 * The screen a clinic owner opens to decide next month's budget.
 *
 * Deliberately absent: impressions, clicks, page views. Those are numbers the
 * ad platform already shows and nobody can act on — this is a clinic operating
 * system, not an analytics tool. Every row here ends in money.
 */
function GrowthOverview({ data }) {
  const t = data.totals;
  const ai = data.ai || {};
  const conf = data.confirmation || {};
  const channels = data.channels || [];
  const revenuePerLead = t.leads ? t.revenue / t.leads : 0;

  // Bars are drawn against the widest stage rather than a fixed scale, so the
  // drop-off between steps is what the eye reads.
  const widest = Math.max(t.leads, 1);
  const stages = [
    { label: 'Lead', value: t.leads, pct: 100 },
    { label: 'Đặt lịch', value: t.bookings, pct: (t.bookings / widest) * 100,
      drop: t.lead_to_booking_percent },
    { label: 'Đến khám', value: t.visits, pct: (t.visits / widest) * 100,
      drop: t.booking_to_visit_percent },
  ];

  return (
    <div className="card-table-wrapper" style={{ padding: 24, marginBottom: 18 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', gap: 8 }}>
        <h2 style={{ margin: 0, fontSize: 16 }}>Tăng trưởng</h2>
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
          {data.range.start_date} → {data.range.end_date}
        </span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(140px,1fr))', gap: 16, margin: '18px 0 26px' }}>
        {[
          ['Lead', t.leads, null],
          ['Đặt lịch', t.bookings, `${t.lead_to_booking_percent}% từ lead`],
          ['Đến khám', t.visits, `${t.booking_to_visit_percent}% từ đặt lịch`],
          ['Doanh thu', fmtShort(t.revenue) + 'đ', `${fmtShort(revenuePerLead)}đ / lead`],
        ].map(([label, value, sub]) => (
          <div key={label}>
            <div style={{ fontSize: 26, fontWeight: 700, color: 'var(--dark-color)' }}>{value}</div>
            <div style={{ fontSize: 12.5, color: 'var(--text-muted)' }}>{label}</div>
            {sub && <div style={{ fontSize: 11.5, color: '#0d9488', marginTop: 2 }}>{sub}</div>}
          </div>
        ))}
      </div>

      <div style={{ marginBottom: 26 }}>
        {stages.map((s) => (
          <div key={s.label} style={{ marginBottom: 10 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5, marginBottom: 3 }}>
              <span><b>{s.value}</b> {s.label}</span>
              {s.drop != null && <span style={{ color: 'var(--text-muted)' }}>↓ {s.drop}%</span>}
            </div>
            <div style={{ height: 10, background: '#f1f5f9', borderRadius: 5 }}>
              <div style={{ height: '100%', width: `${Math.max(s.pct, 1)}%`, borderRadius: 5,
                            background: 'linear-gradient(90deg,#0d9488,#14b8a6)' }} />
            </div>
          </div>
        ))}
      </div>

      {/* A slow callback desk and a weak ad channel look identical in a
          conversion rate. This is the line that tells them apart. */}
      {conf.requested > 0 && conf.median_minutes != null && (
        <div style={{
          background: conf.median_minutes > 60 ? '#fef2f2' : '#f0fdfa',
          border: `1px solid ${conf.median_minutes > 60 ? '#fecaca' : '#99f6e4'}`,
          borderRadius: 8, padding: '10px 14px', fontSize: 13, marginBottom: 22,
        }}>
          Trung vị thời gian xác nhận lịch: <b>{conf.median_minutes} phút</b>
          {' · '}đã xác nhận {conf.confirmed}/{conf.requested}
          {conf.over_1h > 0 && <> · <b>{conf.over_1h}</b> ca chờ quá 1 giờ</>}
          {conf.median_minutes > 60 && (
            <div style={{ marginTop: 4, color: '#991b1b' }}>
              Khách đợi lâu sẽ đặt chỗ khác. Đây là vấn đề tốc độ gọi lại, không phải vấn đề quảng cáo.
            </div>
          )}
        </div>
      )}

      <h3 style={{ fontSize: 14, margin: '0 0 10px' }}>Khách đến từ đâu</h3>
      {channels.length === 0 ? (
        <p style={{ fontSize: 13, color: 'var(--text-muted)' }}>
          Chưa có dữ liệu. Gắn thêm <code>?utm_source=facebook&amp;utm_campaign=...</code> vào
          link quảng cáo để biết kênh nào tạo ra doanh thu.
        </p>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>Kênh</th><th style={{ textAlign: 'right' }}>Lead</th>
              <th style={{ textAlign: 'right' }}>Đặt lịch</th>
              <th style={{ textAlign: 'right' }}>Đến</th>
              <th style={{ textAlign: 'right' }}>Doanh thu</th>
              <th style={{ textAlign: 'right' }}>DT / lead</th>
            </tr>
          </thead>
          <tbody>
            {channels.map((c) => (
              <tr key={c.channel + (c.campaign || '')}>
                <td>
                  <b>{c.channel}</b>
                  {c.campaign && <div style={{ fontSize: 11.5, color: 'var(--text-muted)' }}>{c.campaign}</div>}
                </td>
                <td style={{ textAlign: 'right' }}>{c.leads}</td>
                <td style={{ textAlign: 'right' }}>{c.bookings}</td>
                <td style={{ textAlign: 'right' }}>{c.visits}</td>
                <td style={{ textAlign: 'right' }}>{fmtShort(c.revenue)}đ</td>
                {/* The column to compare against cost per lead — everything
                    else on the row is a step towards it. */}
                <td style={{ textAlign: 'right', fontWeight: 700, color: '#0d9488' }}>
                  {fmtShort(c.revenue_per_lead)}đ
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <div style={{ marginTop: 18, paddingTop: 14, borderTop: '1px solid var(--border-color)', fontSize: 13, color: 'var(--text-muted)' }}>
        Trong đó trợ lý AI: <b>{ai.conversations || 0}</b> hội thoại →{' '}
        <b>{ai.leads_captured || 0}</b> lead → <b>{ai.bookings_generated || 0}</b> lịch hẹn
        {' '}({ai.conversion_percent || 0}%) → <b>{fmtShort(ai.revenue || 0)}đ</b>
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
  const [funnel, setFunnel] = useState(null);
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

        // Lead -> Booking -> Visit -> Revenue, by where the patient came from.
        // Owner-only: it is a spending decision, not an operational one.
        if (manager) {
          const fRes = await fetch(`${API_BASE}/reports/funnel`, { headers });
          if (fRes.ok) setFunnel(await fRes.json());
        }

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

      {isManager && funnel && <GrowthOverview data={funnel} />}

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
