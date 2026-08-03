import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { API_BASE, getAuthHeaders } from '../api';
import AdminShell from '../components/AdminShell';

const fmtMoney = (v) => new Intl.NumberFormat('vi-VN').format(v || 0) + 'đ';
const ORIGIN = window.location.origin;

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

function CopyLink({ url }) {
  const [copied, setCopied] = useState(false);
  const copy = () => { navigator.clipboard?.writeText(url); setCopied(true); setTimeout(() => setCopied(false), 1500); };
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 4, maxWidth: 260 }}>
      <code title={url} style={{ fontSize: 11, background: '#f1f5f9', padding: '2px 6px', borderRadius: 4, color: '#0d9488',
        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1, minWidth: 0 }}>{url}</code>
      <button className="btn btn-sm btn-secondary" style={{ fontSize: 10, padding: '2px 6px', flexShrink: 0 }} onClick={copy}>{copied ? '✓' : 'Chép'}</button>
    </div>
  );
}

const EMPTY_CLINIC = {
  clinic_name: '', owner_name: '', owner_email: '', owner_password: '',
  phone: '', address: '', plan_id: '', monthly_fee: '', organization_id: '', seed_demo_catalogue: true,
};
const EMPTY_PLAN = { code: '', name: '', monthly_quota: 200, price: 0, trial_days: 0, is_active: true };

export default function PlatformPage() {
  const [user, setUser] = useState(null);
  const [tab, setTab] = useState('overview');
  const [overview, setOverview] = useState(null);
  const [clinics, setClinics] = useState([]);
  const [orgs, setOrgs] = useState([]);
  const [plans, setPlans] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');
  const [msg, setMsg] = useState('');
  const [form, setForm] = useState(EMPTY_CLINIC);
  const [orgForm, setOrgForm] = useState({ name: '', owner_name: '', owner_email: '', owner_password: '' });
  const [planForm, setPlanForm] = useState(EMPTY_PLAN);
  const [editClinic, setEditClinic] = useState(null); // clinic being edited (modal)
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  const authFail = () => { localStorage.removeItem('caredesk_token'); navigate('/login'); };
  const flash = (m) => { setMsg(m); setTimeout(() => setMsg(''), 4000); };

  const loadAll = async () => {
    const headers = getAuthHeaders();
    const [ov, cl, og, pl] = await Promise.all([
      fetch(`${API_BASE}/platform/overview`, { headers }),
      fetch(`${API_BASE}/platform/clinics`, { headers }),
      fetch(`${API_BASE}/platform/organizations`, { headers }),
      fetch(`${API_BASE}/platform/plans`, { headers }),
    ]);
    if (ov.status === 401) return authFail();
    if (ov.status === 403) { setErr('Tài khoản không có quyền Nhà phát hành.'); return; }
    setOverview((await ov.json()).totals);
    setClinics(await cl.json());
    setOrgs(await og.json());
    setPlans(await pl.json());
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

  const provision = async (e) => {
    e.preventDefault();
    setBusy(true); setErr('');
    try {
      const body = {
        ...form,
        plan_id: form.plan_id === '' ? null : Number(form.plan_id),
        monthly_fee: form.monthly_fee === '' ? null : Number(form.monthly_fee),
        organization_id: form.organization_id === '' ? null : Number(form.organization_id),
      };
      const res = await fetch(`${API_BASE}/platform/clinics`, { method: 'POST', headers: getAuthHeaders(), body: JSON.stringify(body) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Không tạo được phòng khám');
      flash(`Đã tạo phòng khám "${data.name}" — link công khai: ${ORIGIN}/book/${data.org_slug}`);
      setForm(EMPTY_CLINIC);
      await loadAll();
      setTab('clinics');
    } catch (e2) { setErr(e2.message); }
    finally { setBusy(false); }
  };

  const patchClinic = async (id, patch, label) => {
    setErr('');
    try {
      const res = await fetch(`${API_BASE}/platform/clinics/${id}`, { method: 'PATCH', headers: getAuthHeaders(), body: JSON.stringify(patch) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Cập nhật thất bại');
      flash(label || 'Đã cập nhật.');
      await loadAll();
      return data;
    } catch (e2) { setErr(e2.message); }
  };

  const saveEdit = async (e) => {
    e.preventDefault();
    setBusy(true);
    const c = editClinic;
    const patch = {
      name: c.name, phone: c.phone, address: c.address, og_image_url: c.og_image_url || '',
      plan_id: c.plan_id ? Number(c.plan_id) : null,
      monthly_fee: c.monthly_fee === '' ? null : Number(c.monthly_fee),
      ai_quota_monthly: c.ai_quota_monthly === '' ? null : Number(c.ai_quota_monthly),
      organization_id: c.organization_id === '' || c.organization_id == null ? 0 : Number(c.organization_id),
    };
    // Only regenerate the slug (and its random token) if the admin actually changed it,
    // so a normal edit never breaks the existing public link.
    if ((c.slug || '') !== (c._origSlug || '')) patch.slug = c.slug;
    const ok = await patchClinic(c.clinic_id, patch, 'Đã lưu phòng khám.');
    setBusy(false);
    if (ok) setEditClinic(null);
  };

  const createOrg = async (e) => {
    e.preventDefault();
    setBusy(true); setErr('');
    try {
      const res = await fetch(`${API_BASE}/platform/organizations`, { method: 'POST', headers: getAuthHeaders(), body: JSON.stringify(orgForm) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Không tạo được chuỗi');
      flash(`Đã tạo chuỗi "${data.name}" — link công khai: ${ORIGIN}/book/${data.slug}`);
      setOrgForm({ name: '', owner_name: '', owner_email: '', owner_password: '' });
      await loadAll();
    } catch (e2) { setErr(e2.message); }
    finally { setBusy(false); }
  };

  const createPlan = async (e) => {
    e.preventDefault();
    setBusy(true); setErr('');
    try {
      const res = await fetch(`${API_BASE}/platform/plans`, { method: 'POST', headers: getAuthHeaders(), body: JSON.stringify(planForm) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Không tạo được gói');
      flash(`Đã tạo gói "${data.name}".`);
      setPlanForm(EMPTY_PLAN);
      await loadAll();
    } catch (e2) { setErr(e2.message); }
    finally { setBusy(false); }
  };

  const patchPlan = async (id, patch, label) => {
    setErr('');
    try {
      const res = await fetch(`${API_BASE}/platform/plans/${id}`, { method: 'PATCH', headers: getAuthHeaders(), body: JSON.stringify(patch) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Cập nhật gói thất bại');
      flash(label || 'Đã cập nhật gói.');
      await loadAll();
    } catch (e2) { setErr(e2.message); }
  };

  if (loading) return <div style={{ padding: 40, textAlign: 'center' }}>Đang tải...</div>;

  const tabs = [
    ['overview', '📊 Tổng quan'],
    ['clinics', '🏥 Phòng khám'],
    ['plans', '💳 Gói cước'],
    ['orgs', '🔗 Chuỗi phòng khám'],
  ];

  return (
    <AdminShell user={user} badge="Khu vực Nhà phát hành" title="Bảng điều khiển Nhà phát hành"
      subtitle="Quản lý toàn bộ phòng khám đang bán — tạo, sửa, đổi gói, tạm ngưng, link riêng, doanh thu nền tảng.">
      {err && <div className="login-error" style={{ marginBottom: 16 }}><span>{err}</span></div>}
      {msg && <div style={{ marginBottom: 16, padding: '10px 14px', background: '#ecfdf5', color: 'var(--success-color)', borderRadius: 8, fontSize: 13, fontWeight: 600 }}>{msg}</div>}

      <div style={{ display: 'flex', gap: 8, marginBottom: 20, flexWrap: 'wrap' }}>
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
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Số chuỗi: <b>{overview.organizations}</b> · Số gói cước: <b>{plans.length}</b></div>
        </>
      )}

      {tab === 'clinics' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.5fr) minmax(0, 1fr)', gap: 24, alignItems: 'start' }}>
          <div className="card-table-wrapper" style={{ marginBottom: 0, minWidth: 0, overflowX: 'auto' }}>
            <div className="card-header"><h2>Danh sách phòng khám ({clinics.length})</h2></div>
            <table className="custom-table">
              <thead><tr><th>Phòng khám & Link</th><th>Gói / Phí</th><th>DT tháng</th><th>TT</th><th>Thao tác</th></tr></thead>
              <tbody>
                {clinics.map(c => (
                  <tr key={c.clinic_id}>
                    <td>
                      <div style={{ fontWeight: 600 }}>{c.name}</div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                        {c.owner_email || '—'} · {c.patients} BN{c.organization_id ? ` · chuỗi #${c.organization_id}` : ''}
                        {c.trial_ends_at ? ' · 🎁 dùng thử' : ''}
                      </div>
                      {c.org_slug && <CopyLink url={`${ORIGIN}/book/${c.org_slug}`} />}
                    </td>
                    <td>
                      <span className="badge confirmed" style={{ textTransform: 'uppercase' }}>{c.plan}</span>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>{fmtMoney(c.monthly_fee)}/th · {c.ai_quota_monthly} tin</div>
                    </td>
                    <td>
                      <div style={{ fontWeight: 600 }}>{fmtMoney(c.revenue_this_period)}</div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>AI: {fmtMoney(c.ai_revenue_this_period)}</div>
                    </td>
                    <td><span className={`badge ${c.is_active ? 'completed' : 'cancelled'}`}>{c.is_active ? 'ON' : 'Ngưng'}</span></td>
                    <td>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                        <button className="btn btn-sm btn-primary" style={{ fontSize: 10 }} onClick={() => setEditClinic({ ...c, _origSlug: c.slug })}>Sửa</button>
                        <button className={`btn btn-sm ${c.is_active ? 'btn-danger' : 'btn-secondary'}`} style={{ fontSize: 10 }}
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
              <input className="form-control" placeholder="Tên phòng khám *" required value={form.clinic_name} onChange={e => setForm({ ...form, clinic_name: e.target.value })} />
              <input className="form-control" placeholder="Địa chỉ" value={form.address} onChange={e => setForm({ ...form, address: e.target.value })} />
              <input className="form-control" placeholder="SĐT phòng khám" value={form.phone} onChange={e => setForm({ ...form, phone: e.target.value })} />
              <hr style={{ border: 'none', borderTop: '1px solid var(--border-color)', margin: '2px 0' }} />
              <input className="form-control" placeholder="Tên chủ phòng khám *" required value={form.owner_name} onChange={e => setForm({ ...form, owner_name: e.target.value })} />
              <input className="form-control" type="email" placeholder="Email đăng nhập của chủ *" required value={form.owner_email} onChange={e => setForm({ ...form, owner_email: e.target.value })} />
              <input className="form-control" placeholder="Mật khẩu khởi tạo *" required value={form.owner_password} onChange={e => setForm({ ...form, owner_password: e.target.value })} />
              <div style={{ display: 'flex', gap: 8 }}>
                <select className="form-control" value={form.plan_id} onChange={e => setForm({ ...form, plan_id: e.target.value })} required>
                  <option value="">— Chọn gói —</option>
                  {plans.filter(p => p.is_active).map(p => (
                    <option key={p.id} value={p.id}>{p.name} ({fmtMoney(p.price)}/th{p.trial_days ? `, thử ${p.trial_days}n` : ''})</option>
                  ))}
                </select>
                <input className="form-control" type="number" placeholder="Ghi đè phí (đ)" value={form.monthly_fee} onChange={e => setForm({ ...form, monthly_fee: e.target.value })} />
              </div>
              <select className="form-control" value={form.organization_id} onChange={e => setForm({ ...form, organization_id: e.target.value })}>
                <option value="">— Không thuộc chuỗi —</option>
                {orgs.map(o => <option key={o.id} value={o.id}>Chuỗi: {o.name}</option>)}
              </select>
              <label style={{ fontSize: 12, display: 'flex', gap: 6, alignItems: 'center', color: 'var(--text-muted)' }}>
                <input type="checkbox" checked={form.seed_demo_catalogue} onChange={e => setForm({ ...form, seed_demo_catalogue: e.target.checked })} />
                Tạo sẵn cơ sở/dịch vụ/bác sĩ mẫu để demo ngay
              </label>
              <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? 'Đang tạo...' : 'Tạo phòng khám'}</button>
            </form>
          </div>
        </div>
      )}

      {tab === 'plans' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.5fr) minmax(0, 1fr)', gap: 24, alignItems: 'start' }}>
          <div className="card-table-wrapper" style={{ marginBottom: 0, minWidth: 0, overflowX: 'auto' }}>
            <div className="card-header"><h2>Gói cước ({plans.length})</h2></div>
            <table className="custom-table">
              <thead><tr><th>Gói</th><th>Số tin/tháng</th><th>Giá/tháng</th><th>Dùng thử</th><th>TT</th></tr></thead>
              <tbody>
                {plans.map(p => (
                  <tr key={p.id}>
                    <td><div style={{ fontWeight: 600 }}>{p.name}</div><div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{p.code}</div></td>
                    <td>
                      <input className="form-control" style={{ width: 90, padding: '4px 8px', fontSize: 12 }} type="number" defaultValue={p.monthly_quota}
                        onBlur={e => Number(e.target.value) !== p.monthly_quota && patchPlan(p.id, { monthly_quota: Number(e.target.value) })} />
                    </td>
                    <td>
                      <input className="form-control" style={{ width: 110, padding: '4px 8px', fontSize: 12 }} type="number" defaultValue={p.price}
                        onBlur={e => Number(e.target.value) !== p.price && patchPlan(p.id, { price: Number(e.target.value) })} />
                    </td>
                    <td>
                      <input className="form-control" style={{ width: 64, padding: '4px 8px', fontSize: 12 }} type="number" defaultValue={p.trial_days}
                        onBlur={e => Number(e.target.value) !== p.trial_days && patchPlan(p.id, { trial_days: Number(e.target.value) })} /> ngày
                    </td>
                    <td>
                      <button className={`btn btn-sm ${p.is_active ? 'btn-secondary' : 'btn-danger'}`} style={{ fontSize: 10 }}
                        onClick={() => patchPlan(p.id, { is_active: !p.is_active }, 'Đã đổi trạng thái gói.')}>
                        {p.is_active ? 'Bật' : 'Tắt'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div style={{ padding: '10px 16px', fontSize: 11, color: 'var(--text-muted)' }}>Sửa số/giá trực tiếp rồi click ra ngoài để lưu.</div>
          </div>

          <div className="card-table-wrapper" style={{ marginBottom: 0 }}>
            <div className="card-header"><h2>➕ Tạo gói mới</h2></div>
            <form onSubmit={createPlan} style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 10 }}>
              <input className="form-control" placeholder="Mã gói (vd: vip) *" required value={planForm.code} onChange={e => setPlanForm({ ...planForm, code: e.target.value })} />
              <input className="form-control" placeholder="Tên hiển thị *" required value={planForm.name} onChange={e => setPlanForm({ ...planForm, name: e.target.value })} />
              <label style={{ fontSize: 12, color: 'var(--text-muted)' }}>Số hội thoại AI/tháng
                <input className="form-control" type="number" value={planForm.monthly_quota} onChange={e => setPlanForm({ ...planForm, monthly_quota: Number(e.target.value) })} />
              </label>
              <label style={{ fontSize: 12, color: 'var(--text-muted)' }}>Giá/tháng (đ)
                <input className="form-control" type="number" value={planForm.price} onChange={e => setPlanForm({ ...planForm, price: Number(e.target.value) })} />
              </label>
              <label style={{ fontSize: 12, color: 'var(--text-muted)' }}>Số ngày dùng thử (0 = không)
                <input className="form-control" type="number" value={planForm.trial_days} onChange={e => setPlanForm({ ...planForm, trial_days: Number(e.target.value) })} />
              </label>
              <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? 'Đang tạo...' : 'Tạo gói'}</button>
            </form>
          </div>
        </div>
      )}

      {tab === 'orgs' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.5fr) minmax(0, 1fr)', gap: 24, alignItems: 'start' }}>
          <div className="card-table-wrapper" style={{ marginBottom: 0, minWidth: 0, overflowX: 'auto' }}>
            <div className="card-header"><h2>Chuỗi phòng khám ({orgs.length})</h2></div>
            <table className="custom-table">
              <thead><tr><th>Chuỗi & Link</th><th>Chủ chuỗi</th><th>Số PK</th></tr></thead>
              <tbody>
                {orgs.map(o => (
                  <tr key={o.id}>
                    <td>
                      <div style={{ fontWeight: 600 }}>{o.name}</div>
                      {o.slug && <CopyLink url={`${ORIGIN}/book/${o.slug}`} />}
                    </td>
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
              <input className="form-control" placeholder="Tên chuỗi *" required value={orgForm.name} onChange={e => setOrgForm({ ...orgForm, name: e.target.value })} />
              <input className="form-control" placeholder="Tên chủ chuỗi *" required value={orgForm.owner_name} onChange={e => setOrgForm({ ...orgForm, owner_name: e.target.value })} />
              <input className="form-control" type="email" placeholder="Email chủ chuỗi *" required value={orgForm.owner_email} onChange={e => setOrgForm({ ...orgForm, owner_email: e.target.value })} />
              <input className="form-control" placeholder="Mật khẩu khởi tạo *" required value={orgForm.owner_password} onChange={e => setOrgForm({ ...orgForm, owner_password: e.target.value })} />
              <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? 'Đang tạo...' : 'Tạo chuỗi'}</button>
            </form>
          </div>
        </div>
      )}

      {/* Edit clinic modal */}
      {editClinic && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(15,23,42,.55)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50, padding: 20 }}
          onClick={() => setEditClinic(null)}>
          <div className="card-table-wrapper" style={{ marginBottom: 0, width: 460, maxHeight: '90vh', overflowY: 'auto' }} onClick={e => e.stopPropagation()}>
            <div className="card-header"><h2>Sửa phòng khám #{editClinic.clinic_id}</h2></div>
            <form onSubmit={saveEdit} style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 10 }}>
              <label style={{ fontSize: 12, color: 'var(--text-muted)' }}>Tên phòng khám
                <input className="form-control" value={editClinic.name || ''} onChange={e => setEditClinic({ ...editClinic, name: e.target.value })} /></label>
              <label style={{ fontSize: 12, color: 'var(--text-muted)' }}>SĐT
                <input className="form-control" value={editClinic.phone || ''} onChange={e => setEditClinic({ ...editClinic, phone: e.target.value })} /></label>
              <label style={{ fontSize: 12, color: 'var(--text-muted)' }}>Địa chỉ
                <input className="form-control" value={editClinic.address || ''} onChange={e => setEditClinic({ ...editClinic, address: e.target.value })} /></label>
              <label style={{ fontSize: 12, color: 'var(--text-muted)' }}>Ảnh chia sẻ mạng xã hội (og:image) — URL ảnh ~1200×630
                <input className="form-control" placeholder="https://..." value={editClinic.og_image_url || ''} onChange={e => setEditClinic({ ...editClinic, og_image_url: e.target.value })} />
                <div style={{ fontSize: 10, marginTop: 2 }}>Facebook/Zalo bỏ qua ảnh nhỏ hơn 200×200. Để trống sẽ dùng tạm logo.</div></label>
              <label style={{ fontSize: 12, color: 'var(--text-muted)' }}>Mã link phòng khám (slug) — đổi sẽ sinh mã ngẫu nhiên mới & tạo link mới
                <input className="form-control" value={editClinic.slug || ''} onChange={e => setEditClinic({ ...editClinic, slug: e.target.value })} />
                {editClinic.org_slug && <div style={{ fontSize: 10, marginTop: 2 }}>Link công khai: /book/{editClinic.org_slug}</div>}</label>
              <div style={{ display: 'flex', gap: 8 }}>
                <label style={{ fontSize: 12, color: 'var(--text-muted)', flex: 1 }}>Gói
                  <select className="form-control" value={editClinic.plan_id || ''} onChange={e => setEditClinic({ ...editClinic, plan_id: e.target.value })}>
                    <option value="">—</option>
                    {plans.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                  </select></label>
                <label style={{ fontSize: 12, color: 'var(--text-muted)', flex: 1 }}>Phí/tháng
                  <input className="form-control" type="number" value={editClinic.monthly_fee ?? ''} onChange={e => setEditClinic({ ...editClinic, monthly_fee: e.target.value })} /></label>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <label style={{ fontSize: 12, color: 'var(--text-muted)', flex: 1 }}>Số tin/tháng
                  <input className="form-control" type="number" value={editClinic.ai_quota_monthly ?? ''} onChange={e => setEditClinic({ ...editClinic, ai_quota_monthly: e.target.value })} /></label>
                <label style={{ fontSize: 12, color: 'var(--text-muted)', flex: 1 }}>Chuỗi
                  <select className="form-control" value={editClinic.organization_id || ''} onChange={e => setEditClinic({ ...editClinic, organization_id: e.target.value })}>
                    <option value="">— Không —</option>
                    {orgs.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
                  </select></label>
              </div>
              <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
                <button className="btn btn-secondary" type="button" style={{ flex: 1 }} onClick={() => setEditClinic(null)}>Hủy</button>
                <button className="btn btn-primary" type="submit" style={{ flex: 1 }} disabled={busy}>{busy ? 'Đang lưu...' : 'Lưu thay đổi'}</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </AdminShell>
  );
}
