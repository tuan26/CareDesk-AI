import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { API_BASE, getAuthHeaders } from '../api';
import AdminShell from '../components/AdminShell';

const fmtMoney = (v) => new Intl.NumberFormat('vi-VN').format(v || 0) + 'đ';

function Stat({ title, value, sub, accent }) {
  return (
    <div className="stat-card" style={accent ? { borderTop: `3px solid ${accent}` } : {}}>
      <div className="stat-info">
        <h3>{title}</h3>
        <div className="stat-number" style={{ fontSize: 22, color: accent || 'var(--dark-color)' }}>{value}</div>
        {sub && <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>{sub}</div>}
      </div>
    </div>
  );
}

export default function OrgPage() {
  const [user, setUser] = useState(null);
  const [org, setOrg] = useState(null);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');
  const navigate = useNavigate();
  const authFail = () => { localStorage.removeItem('caredesk_token'); navigate('/login'); };

  useEffect(() => {
    (async () => {
      try {
        const headers = getAuthHeaders();
        const meRes = await fetch(`${API_BASE}/auth/me`, { headers });
        if (meRes.status === 401) return authFail();
        const me = await meRes.json();
        if (!me.organization_id) { navigate('/'); return; }
        setUser(me);
        const [meOrg, ov] = await Promise.all([
          fetch(`${API_BASE}/org/me`, { headers }),
          fetch(`${API_BASE}/org/overview`, { headers }),
        ]);
        if (ov.status === 403) { setErr('Tài khoản không thuộc chuỗi nào.'); return; }
        setOrg(await meOrg.json());
        setData(await ov.json());
      } catch { setErr('Lỗi kết nối máy chủ.'); }
      finally { setLoading(false); }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (loading) return <div style={{ padding: 40, textAlign: 'center' }}>Đang tải...</div>;

  const t = data?.totals;
  const clinics = data?.clinics || [];

  return (
    <AdminShell
      user={user}
      badge="Khu vực Chủ chuỗi"
      title={org ? org.name : 'Chuỗi phòng khám'}
      subtitle="Tổng hợp toàn chuỗi — số liệu gộp từ mọi phòng khám thành viên trong tháng này."
    >
      {err && <div className="login-error" style={{ marginBottom: 16 }}><span>{err}</span></div>}

      {t && (
        <div className="stats-grid">
          <Stat title="Số phòng khám" accent="var(--primary-color)" value={t.clinics}
            sub={`Đang hoạt động: ${t.active_clinics}${t.suspended_clinics ? ` · Tạm ngưng: ${t.suspended_clinics}` : ''}`} />
          <Stat title="Doanh thu toàn chuỗi (tháng)" accent="#10b981" value={fmtMoney(t.revenue_this_period)}
            sub={`AI tạo ra: ${fmtMoney(t.ai_revenue_this_period)}`} />
          <Stat title="Bệnh nhân toàn chuỗi" accent="#3b82f6" value={t.total_patients}
            sub={`Lịch hẹn tháng: ${t.appointments_this_period}`} />
          <Stat title="Hội thoại AI (tháng)" accent="#f59e0b" value={t.conversations_this_period}
            sub="Tổng trên tất cả phòng khám" />
        </div>
      )}

      <div className="card-table-wrapper" style={{ marginBottom: 0 }}>
        <div className="card-header"><h2>Chi tiết theo phòng khám</h2></div>
        <table className="custom-table">
          <thead>
            <tr><th>Phòng khám</th><th>Gói</th><th>Bệnh nhân</th><th>Lịch hẹn (tháng)</th><th>Doanh thu (tháng)</th><th>AI tạo ra</th><th>Trạng thái</th></tr>
          </thead>
          <tbody>
            {clinics.map(c => (
              <tr key={c.clinic_id}>
                <td>
                  <div style={{ fontWeight: 600 }}>{c.name}</div>
                  {c.slug && c.org_slug && (
                    <a href={`/org/${c.org_slug}/clinics/${c.slug}/chat`} target="_blank" rel="noreferrer"
                      style={{ fontSize: 11, color: 'var(--primary-color)' }}>🔗 Link chat công khai</a>
                  )}
                </td>
                <td><span className="badge confirmed" style={{ textTransform: 'uppercase' }}>{c.plan}</span></td>
                <td>{c.patients}</td>
                <td>{c.appointments_this_period} <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>({c.completed_this_period} xong)</span></td>
                <td style={{ fontWeight: 600 }}>{fmtMoney(c.revenue_this_period)}</td>
                <td>{fmtMoney(c.ai_revenue_this_period)}</td>
                <td><span className={`badge ${c.is_active ? 'completed' : 'cancelled'}`}>{c.is_active ? 'Hoạt động' : 'Tạm ngưng'}</span></td>
              </tr>
            ))}
            {clinics.length === 0 && <tr><td colSpan={7} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 24 }}>Chuỗi chưa có phòng khám nào.</td></tr>}
          </tbody>
        </table>
      </div>
    </AdminShell>
  );
}
