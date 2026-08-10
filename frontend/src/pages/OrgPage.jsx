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
  const [entering, setEntering] = useState(0);
  const navigate = useNavigate();
  const authFail = () => { localStorage.removeItem('caredesk_token'); navigate('/login'); };

  // Step into a clinic: get a scoped token, swap it in, open the full clinic dashboard.
  const manageClinic = async (clinicId, clinicName) => {
    setEntering(clinicId); setErr('');
    try {
      const res = await fetch(`${API_BASE}/org/enter-clinic/${clinicId}`, { method: 'POST', headers: getAuthHeaders() });
      const d = await res.json();
      if (!res.ok) throw new Error(d.detail || 'Không vào được phòng khám');
      localStorage.setItem('caredesk_org_token', localStorage.getItem('caredesk_token')); // keep chain-owner token
      localStorage.setItem('caredesk_token', d.access_token); // scoped clinic token
      localStorage.setItem('caredesk_active_clinic', JSON.stringify({ id: clinicId, name: clinicName, orgSlug: org?.slug }));
      navigate('/');
    } catch (e) { setErr(e.message); }
    finally { setEntering(0); }
  };

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
        // The chain console ships switched off (services/features.py). The API
        // answers 404 rather than 403 so a disabled area looks absent instead of
        // forbidden — say so plainly rather than rendering an empty console.
        if (ov.status === 404) {
          setErr('Tính năng quản lý chuỗi chưa được bật cho tài khoản này.');
          return;
        }
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
            <tr><th>Phòng khám</th><th>Gói</th><th>BN</th><th>Lịch hẹn</th><th>Doanh thu</th><th>AI</th><th>TT</th><th>Quản lý</th></tr>
          </thead>
          <tbody>
            {clinics.map(c => (
              <tr key={c.clinic_id}>
                <td>
                  <div style={{ fontWeight: 600 }}>{c.name}</div>
                  {c.slug && c.org_slug && (
                    <a href={`/book/${c.org_slug}`} target="_blank" rel="noreferrer"
                      style={{ fontSize: 11, color: 'var(--primary-color)' }}>🔗 Link phòng khám công khai</a>
                  )}
                </td>
                <td><span className="badge confirmed" style={{ textTransform: 'uppercase' }}>{c.plan}</span></td>
                <td>{c.patients}</td>
                <td>{c.appointments_this_period} <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>({c.completed_this_period}✓)</span></td>
                <td style={{ fontWeight: 600 }}>{fmtMoney(c.revenue_this_period)}</td>
                <td>{fmtMoney(c.ai_revenue_this_period)}</td>
                <td><span className={`badge ${c.is_active ? 'completed' : 'cancelled'}`}>{c.is_active ? 'ON' : 'Ngưng'}</span></td>
                <td>
                  <button className="btn btn-sm btn-primary" style={{ fontSize: 11 }} disabled={entering === c.clinic_id}
                    onClick={() => manageClinic(c.clinic_id, c.name)}>
                    {entering === c.clinic_id ? '...' : 'Quản lý →'}
                  </button>
                </td>
              </tr>
            ))}
            {clinics.length === 0 && <tr><td colSpan={8} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 24 }}>Chuỗi chưa có phòng khám nào.</td></tr>}
          </tbody>
        </table>
      </div>
    </AdminShell>
  );
}
