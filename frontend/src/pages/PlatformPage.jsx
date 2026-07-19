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

const EMPTY_CLINIC = {
  clinic_name: '', owner_name: '', owner_email: '', owner_password: '',
  phone: '', address: '', plan: 'free', monthly_fee: '', organization_id: '', seed_demo_catalogue: true,
};

export default function PlatformPage() {
  const [user, setUser] = useState(null);
  const [tab, setTab] = useState('overview');
  const [overview, setOverview] = useState(null);
  const [clinics, setClinics] = useState([]);
  const [orgs, setOrgs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');
  const [msg, setMsg] = useState('');
  const [form, setForm] = useState(EMPTY_CLINIC);
  const [orgForm, setOrgForm] = useState({ name: '', owner_name: '', owner_email: '', owner_password: '' });
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  const authFail = () => { localStorage.removeItem('caredesk_token'); navigate('/login'); };

  const loadAll = async () => {
    const headers = getAuthHeaders();
    const [ov, cl, og] = await Promise.all([
      fetch(`${API_BASE}/platform/overview`, { headers }),
      fetch(`${API_BASE}/platform/clinics`, { headers }),
      fetch(`${API_BASE}/platform/organizations`, { headers }),
    ]);
    if (ov.status === 401) return authFail();
    if (ov.status === 403) { setErr('Tài khoản không có quyền Nhà phát hành.'); return; }
    setOverview((await ov.json()).totals);
    setClinics(await cl.json());
    setOrgs(await og.json());
  };

  useEffect(() => {
    (async () => {
      try {
        const meRes = await fetch(`${API_BASE}/auth/me`, { headers: getAuthHeaders() });
        if (meRes.status === 401) return authFail();
        const me = await meRes.json();
        if (!me.is_platform_admin) { navigate('/'); return; }
        setUser(me);
        await loadAll();
      } catch { setErr('Lỗi kết nối máy chủ.'); }
      finally { setLoading(false); }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const flash = (m) => { setMsg(m); setTimeout(() => setMsg(''), 4000); };

  const provision = async (e) => {
    e.preventDefault();
    setBusy(true); setErr('');
    try {
      const body = {
        ...form,
        monthly_fee: form.monthly_fee === '' ? null : Number(form.monthly_fee),
        organization_id: form.organization_id === '' ? null : Number(form.organization_id),
      };
      const res = await fetch(`${API_BASE}/platform/clinics`, {
        method: 'POST', headers: getAuthHeaders(), body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Không tạo được phòng khám');
      flash(`Đã tạo phòng khám "${data.name}" (#${data.clinic_id}).`);
      setForm(EMPTY_CLINIC);
      await loadAll();
      setTab('clinics');
    } catch (e2) { setErr(e2.message); }
    finally { setBusy(false); }
  };

  const patchClinic = async (id, patch, label) => {
    setErr('');
    try {
      const res = await fetch(`${API_BASE}/platform/clinics/${id}`, {
        method: 'PATCH', headers: getAuthHeaders(), body: JSON.stringify(patch),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Cập nhật thất bại');
      flash(label || 'Đã cập nhật.');
      await loadAll();
    } catch (e2) { setErr(e2.message); }
  };

  const createOrg = async (e) => {
    e.preventDefault();
    setBusy(true); setErr('');
    try {
      const res = await fetch(`${API_BASE}/platform/organizations`, {
        method: 'POST', headers: getAuthHeaders(), body: JSON.stringify(orgForm),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Không tạo được chuỗi');
      flash(`Đã tạo chuỗi "${data.name}".`);
      setOrgForm({ name: '', owner_name: '', owner_email: '', owner_password: '' });
      await loadAll();
    } catch (e2) { setErr(e2.message); }
    finally { setBusy(false); }
  };

  if (loading) return <div style={{ padding: 40, textAlign: 'center' }}>Đang tải...</div>;

  const tabs = [
    ['overview', '📊 Tổng quan'],
    ['clinics', '🏥 Phòng khám'],
    ['orgs', '🔗 Chuỗi phòng khám'],
  ];

  return (
    <AdminShell
      user={user}
      badge="Khu vực Nhà phát hành"
      title="Bảng điều khiển Nhà phát hành"
      subtitle="Quản lý toàn bộ phòng khám đang bán — tạo, đổi gói, tạm ngưng, theo dõi doanh thu nền tảng."
    >
      {err && <div className="login-error" style={{ marginBottom: 16 }}><span>{err}</span></div>}
      {msg && <div style={{ marginBottom: 16, padding: '10px 14px', background: '#ecfdf5', color: 'var(--success-color)', borderRadius: 8, fontSize: 13, fontWeight: 600 }}>{msg}</div>}

      <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
        {tabs.map(([k, label]) => (
          <button key={k} className={`btn btn-sm ${tab === k ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setTab(k)}>{label}</button>
        ))}
      </div>

      {tab === 'overview' && overview && (
        <>
          <div className="stats-grid">
            <Stat title="Phòng khám" accent="var(--primary-color)" value={overview.clinics}
              sub={`Đang hoạt động: ${overview.active_clinics} · Tạm ngưng: ${overview.suspended_clinics}`} />
            <Stat title="Doanh thu định kỳ (MRR)" accent="#10b981" value={fmtMoney(overview.mrr)}
              sub="Tổng phí gói/tháng từ phòng khám đang hoạt động" />
            <Stat title="Doanh thu tháng (toàn hệ thống)" accent="#3b82f6" value={fmtMoney(overview.revenue_this_period)}
              sub={`Trong đó AI tạo ra: ${fmtMoney(overview.ai_revenue_this_period)}`} />
            <Stat title="Bệnh nhân & Hội thoại" accent="#f59e0b" value={overview.total_patients}
              sub={`Hội thoại tháng: ${overview.conversations_this_period} · Lịch hẹn: ${overview.appointments_this_period}`} />
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Số chuỗi phòng khám: <b>{overview.organizations}</b></div>
        </>
      )}

      {tab === 'clinics' && (
        <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 24, alignItems: 'start' }}>
          <div className="card-table-wrapper" style={{ marginBottom: 0 }}>
            <div className="card-header"><h2>Danh sách phòng khám ({clinics.length})</h2></div>
            <table className="custom-table">
              <thead>
                <tr><th>Phòng khám</th><th>Gói</th><th>Doanh thu tháng</th><th>Trạng thái</th><th>Thao tác</th></tr>
              </thead>
              <tbody>
                {clinics.map(c => (
                  <tr key={c.clinic_id}>
                    <td>
                      <div style={{ fontWeight: 600 }}>{c.name}</div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                        {c.owner_email || '—'} · {c.patients} BN{c.organization_id ? ` · chuỗi #${c.organization_id}` : ''}
                      </div>
                    </td>
                    <td>
                      <span className="badge confirmed" style={{ textTransform: 'uppercase' }}>{c.plan}</span>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>{fmtMoney(c.monthly_fee)}/th</div>
                    </td>
                    <td>
                      <div style={{ fontWeight: 600 }}>{fmtMoney(c.revenue_this_period)}</div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>AI: {fmtMoney(c.ai_revenue_this_period)}</div>
                    </td>
                    <td><span className={`badge ${c.is_active ? 'completed' : 'cancelled'}`}>{c.is_active ? 'Hoạt động' : 'Tạm ngưng'}</span></td>
                    <td>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                        <button className="btn btn-sm btn-secondary" style={{ fontSize: 10 }}
                          onClick={() => patchClinic(c.clinic_id, { plan: c.plan === 'pro' ? 'free' : 'pro' }, 'Đã đổi gói.')}>
                          → {c.plan === 'pro' ? 'Hạ Free' : 'Nâng Pro'}
                        </button>
                        <button className={`btn btn-sm ${c.is_active ? 'btn-danger' : 'btn-primary'}`} style={{ fontSize: 10 }}
                          onClick={() => patchClinic(c.clinic_id, { is_active: !c.is_active }, c.is_active ? 'Đã tạm ngưng.' : 'Đã mở lại.')}>
                          {c.is_active ? 'Tạm ngưng' : 'Mở lại'}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="card-table-wrapper" style={{ marginBottom: 0 }}>
            <div className="card-header"><h2>➕ Tạo phòng khám cho khách</h2></div>
            <form onSubmit={provision} style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 10 }}>
              <input className="form-control" placeholder="Tên phòng khám *" required
                value={form.clinic_name} onChange={e => setForm({ ...form, clinic_name: e.target.value })} />
              <input className="form-control" placeholder="Địa chỉ"
                value={form.address} onChange={e => setForm({ ...form, address: e.target.value })} />
              <input className="form-control" placeholder="SĐT phòng khám"
                value={form.phone} onChange={e => setForm({ ...form, phone: e.target.value })} />
              <hr style={{ border: 'none', borderTop: '1px solid var(--border-color)', margin: '2px 0' }} />
              <input className="form-control" placeholder="Tên chủ phòng khám *" required
                value={form.owner_name} onChange={e => setForm({ ...form, owner_name: e.target.value })} />
              <input className="form-control" type="email" placeholder="Email đăng nhập của chủ *" required
                value={form.owner_email} onChange={e => setForm({ ...form, owner_email: e.target.value })} />
              <input className="form-control" type="text" placeholder="Mật khẩu khởi tạo *" required
                value={form.owner_password} onChange={e => setForm({ ...form, owner_password: e.target.value })} />
              <div style={{ display: 'flex', gap: 8 }}>
                <select className="form-control" value={form.plan} onChange={e => setForm({ ...form, plan: e.target.value })}>
                  <option value="free">Gói Free</option>
                  <option value="pro">Gói Pro</option>
                </select>
                <input className="form-control" type="number" placeholder="Phí/tháng (đ)"
                  value={form.monthly_fee} onChange={e => setForm({ ...form, monthly_fee: e.target.value })} />
              </div>
              <select className="form-control" value={form.organization_id}
                onChange={e => setForm({ ...form, organization_id: e.target.value })}>
                <option value="">— Không thuộc chuỗi —</option>
                {orgs.map(o => <option key={o.id} value={o.id}>Chuỗi: {o.name}</option>)}
              </select>
              <label style={{ fontSize: 12, display: 'flex', gap: 6, alignItems: 'center', color: 'var(--text-muted)' }}>
                <input type="checkbox" checked={form.seed_demo_catalogue}
                  onChange={e => setForm({ ...form, seed_demo_catalogue: e.target.checked })} />
                Tạo sẵn cơ sở/dịch vụ/bác sĩ mẫu để demo ngay
              </label>
              <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? 'Đang tạo...' : 'Tạo phòng khám'}</button>
            </form>
          </div>
        </div>
      )}

      {tab === 'orgs' && (
        <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 24, alignItems: 'start' }}>
          <div className="card-table-wrapper" style={{ marginBottom: 0 }}>
            <div className="card-header"><h2>Chuỗi phòng khám ({orgs.length})</h2></div>
            <table className="custom-table">
              <thead><tr><th>Chuỗi</th><th>Chủ chuỗi</th><th>Số phòng khám</th></tr></thead>
              <tbody>
                {orgs.map(o => (
                  <tr key={o.id}>
                    <td><div style={{ fontWeight: 600 }}>{o.name}</div><div style={{ fontSize: 11, color: 'var(--text-muted)' }}>#{o.id}</div></td>
                    <td style={{ fontSize: 12 }}>{o.owner_email || '—'}</td>
                    <td><span className="badge confirmed">{o.clinic_count}</span></td>
                  </tr>
                ))}
                {orgs.length === 0 && <tr><td colSpan={3} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 24 }}>Chưa có chuỗi nào.</td></tr>}
              </tbody>
            </table>
          </div>
          <div className="card-table-wrapper" style={{ marginBottom: 0 }}>
            <div className="card-header"><h2>➕ Tạo chuỗi mới</h2></div>
            <form onSubmit={createOrg} style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 10 }}>
              <input className="form-control" placeholder="Tên chuỗi *" required
                value={orgForm.name} onChange={e => setOrgForm({ ...orgForm, name: e.target.value })} />
              <input className="form-control" placeholder="Tên chủ chuỗi *" required
                value={orgForm.owner_name} onChange={e => setOrgForm({ ...orgForm, owner_name: e.target.value })} />
              <input className="form-control" type="email" placeholder="Email chủ chuỗi *" required
                value={orgForm.owner_email} onChange={e => setOrgForm({ ...orgForm, owner_email: e.target.value })} />
              <input className="form-control" placeholder="Mật khẩu khởi tạo *" required
                value={orgForm.owner_password} onChange={e => setOrgForm({ ...orgForm, owner_password: e.target.value })} />
              <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? 'Đang tạo...' : 'Tạo chuỗi'}</button>
              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Gán phòng khám vào chuỗi ở tab "Phòng khám" khi tạo mới.</div>
            </form>
          </div>
        </div>
      )}
    </AdminShell>
  );
}
