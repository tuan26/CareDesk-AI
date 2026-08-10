import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { API_BASE, getAuthHeaders } from '../api';

const fmtMoney = (v) => new Intl.NumberFormat('vi-VN').format(v || 0) + 'đ';
const EMPTY_FORM = { name: '', service_id: '', total_sessions: 5, price: '', validity_days: 180, active: true };

export default function PackagesPage() {
  const [packages, setPackages] = useState([]);
  const [patientPackages, setPatientPackages] = useState([]);
  const [services, setServices] = useState([]);
  const [patients, setPatients] = useState([]);
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [showSellModal, setShowSellModal] = useState(false);
  const [sellForm, setSellForm] = useState({ patient_id: '', package_id: '' });
  const navigate = useNavigate();

  const isManager = user && user.role === 'owner';

  const fetchData = async () => {
    try {
      const headers = getAuthHeaders();
      const [meRes, pkgRes, ppRes, svcRes, ptRes] = await Promise.all([
        fetch(`${API_BASE}/auth/me`, { headers }),
        fetch(`${API_BASE}/packages`, { headers }),
        fetch(`${API_BASE}/packages/patient-packages`, { headers }),
        fetch(`${API_BASE}/clinic/services`, { headers }),
        fetch(`${API_BASE}/appointments/patients`, { headers })
      ]);
      if (meRes.status === 401) throw new Error('Unauthorized');
      setUser(await meRes.json());
      setPackages(await pkgRes.json());
      setPatientPackages(await ppRes.json());
      setServices(await svcRes.json());
      setPatients(await ptRes.json());
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

  useEffect(() => { fetchData(); }, [navigate]);

  const openCreate = () => { setEditing(null); setForm({ ...EMPTY_FORM, service_id: services[0]?.id || '' }); setShowModal(true); };
  const openEdit = (pkg) => {
    setEditing(pkg);
    setForm({ name: pkg.name, service_id: pkg.service_id || '', total_sessions: pkg.total_sessions, price: pkg.price, validity_days: pkg.validity_days, active: pkg.active });
    setShowModal(true);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const payload = {
      name: form.name,
      service_id: form.service_id ? parseInt(form.service_id, 10) : null,
      total_sessions: parseInt(form.total_sessions, 10) || 1,
      price: parseFloat(form.price) || 0,
      validity_days: parseInt(form.validity_days, 10) || 180,
      active: form.active
    };
    const url = editing ? `${API_BASE}/packages/${editing.id}` : `${API_BASE}/packages`;
    const res = await fetch(url, { method: editing ? 'PUT' : 'POST', headers: getAuthHeaders(), body: JSON.stringify(payload) });
    if (res.ok) { setShowModal(false); fetchData(); }
    else alert((await res.json().catch(() => null))?.detail || 'Không thể lưu gói.');
  };

  const handleDelete = async (pkg) => {
    if (!window.confirm(`Xóa gói "${pkg.name}"?`)) return;
    const res = await fetch(`${API_BASE}/packages/${pkg.id}`, { method: 'DELETE', headers: getAuthHeaders() });
    if (res.ok || res.status === 204) fetchData();
  };

  const handleSell = async (e) => {
    e.preventDefault();
    const res = await fetch(`${API_BASE}/packages/sell`, {
      method: 'POST', headers: getAuthHeaders(),
      body: JSON.stringify({ patient_id: parseInt(sellForm.patient_id, 10), package_id: parseInt(sellForm.package_id, 10) })
    });
    if (res.ok) { setShowSellModal(false); fetchData(); alert('Đã bán gói thành công — doanh thu đã được ghi nhận!'); }
    else alert((await res.json().catch(() => null))?.detail || 'Không thể bán gói.');
  };

  const handleUseSession = async (pp) => {
    if (!window.confirm(`Trừ 1 buổi của ${pp.patient_name} (${pp.sessions_used}/${pp.sessions_total} đã dùng)?`)) return;
    const res = await fetch(`${API_BASE}/packages/patient-packages/${pp.id}/use-session`, { method: 'POST', headers: getAuthHeaders() });
    if (res.ok) fetchData();
    else alert((await res.json().catch(() => null))?.detail || 'Không thể trừ buổi.');
  };

  const serviceName = (id) => services.find(s => s.id === id)?.name || 'Mọi dịch vụ';

  if (loading) return <div style={{ padding: '24px', textAlign: 'center' }}>Đang tải gói liệu trình...</div>;

  return (
    <div>
      <div className="page-header">
        <div className="page-title">
          <h1>Gói liệu trình</h1>
          <p>Bán gói trả trước — thu tiền sớm, khóa chân khách quay lại. Buổi khám hoàn thành tự động trừ vào gói.</p>
        </div>
        <div style={{ display: 'flex', gap: '10px' }}>
          <button className="btn btn-secondary" onClick={() => { setSellForm({ patient_id: patients[0]?.id || '', package_id: packages[0]?.id || '' }); setShowSellModal(true); }}
            disabled={packages.length === 0 || patients.length === 0}>
            💰 Bán gói cho khách
          </button>
          {isManager && <button className="btn btn-primary" onClick={openCreate}>+ Tạo gói mới</button>}
        </div>
      </div>

      {/* Catalogue */}
      <div className="card-table-wrapper">
        <div className="card-header"><h2>Danh mục gói ({packages.length})</h2></div>
        {packages.length === 0 ? (
          <div style={{ padding: '28px', textAlign: 'center', color: 'var(--text-muted)' }}>
            Chưa có gói nào. Tạo gói đầu tiên — ví dụ "Gói trị mụn 5 buổi".
          </div>
        ) : (
          <table className="custom-table">
            <thead>
              <tr><th>Gói</th><th>Dịch vụ áp dụng</th><th>Số buổi</th><th>Giá gói</th><th>Hạn dùng</th><th>Trạng thái</th>{isManager && <th style={{ width: '130px' }}></th>}</tr>
            </thead>
            <tbody>
              {packages.map((pkg) => (
                <tr key={pkg.id}>
                  <td style={{ fontWeight: 600 }}>{pkg.name}</td>
                  <td>{serviceName(pkg.service_id)}</td>
                  <td>{pkg.total_sessions} buổi</td>
                  <td style={{ fontWeight: 600, color: 'var(--primary-color)' }}>{fmtMoney(pkg.price)}</td>
                  <td>{pkg.validity_days} ngày</td>
                  <td><span className={`badge ${pkg.active ? 'completed' : 'cancelled'}`}>{pkg.active ? 'Đang bán' : 'Ngừng bán'}</span></td>
                  {isManager && (
                    <td>
                      <div style={{ display: 'flex', gap: '6px' }}>
                        <button className="btn btn-secondary btn-sm" onClick={() => openEdit(pkg)}>Sửa</button>
                        <button className="btn btn-danger btn-sm" onClick={() => handleDelete(pkg)}>Xóa</button>
                      </div>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Sold packages */}
      <div className="card-table-wrapper">
        <div className="card-header"><h2>Gói khách đang sở hữu ({patientPackages.length})</h2></div>
        {patientPackages.length === 0 ? (
          <div style={{ padding: '28px', textAlign: 'center', color: 'var(--text-muted)' }}>Chưa bán gói nào cho khách.</div>
        ) : (
          <table className="custom-table">
            <thead>
              <tr><th>Khách hàng</th><th>Gói</th><th>Tiến độ</th><th>Đã trả</th><th>Hết hạn</th><th>Trạng thái</th><th style={{ width: '110px' }}></th></tr>
            </thead>
            <tbody>
              {patientPackages.map((pp) => (
                <tr key={pp.id}>
                  <td>
                    <div style={{ fontWeight: 600 }}>{pp.patient_name}</div>
                    <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{pp.patient_phone}</div>
                  </td>
                  <td>{pp.package_name}</td>
                  <td style={{ minWidth: '140px' }}>
                    <div style={{ fontSize: '12px', marginBottom: '4px' }}>Buổi {pp.sessions_used}/{pp.sessions_total}</div>
                    <div style={{ background: '#f1f5f9', borderRadius: '4px', height: '6px', overflow: 'hidden' }}>
                      <div style={{ width: `${(pp.sessions_used / pp.sessions_total) * 100}%`, height: '100%', background: 'var(--primary-color)' }} />
                    </div>
                  </td>
                  <td>{fmtMoney(pp.amount_paid)}</td>
                  <td style={{ fontSize: '13px' }}>{pp.expires_at ? new Date(pp.expires_at).toLocaleDateString('vi-VN') : '—'}</td>
                  <td>
                    <span className={`badge ${pp.status === 'active' ? 'confirmed' : pp.status === 'used_up' ? 'completed' : 'cancelled'}`}>
                      {pp.status === 'active' ? 'Còn hiệu lực' : pp.status === 'used_up' ? 'Đã dùng hết' : 'Hết hạn'}
                    </span>
                  </td>
                  <td>
                    {pp.status === 'active' && (
                      <button className="btn btn-secondary btn-sm" onClick={() => handleUseSession(pp)}>Trừ 1 buổi</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Create/Edit modal */}
      {showModal && (
        <div className="modal-overlay" onClick={() => setShowModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>{editing ? 'Sửa gói' : 'Tạo gói liệu trình'}</h3>
              <button className="modal-close-btn" onClick={() => setShowModal(false)}>&times;</button>
            </div>
            <form onSubmit={handleSubmit}>
              <div className="modal-body">
                <div className="form-group">
                  <label>Tên gói *</label>
                  <input className="form-control" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
                    placeholder="Gói trị mụn chuyên sâu 5 buổi" required />
                </div>
                <div className="form-group">
                  <label>Dịch vụ áp dụng</label>
                  <select className="form-control" value={form.service_id} onChange={(e) => setForm({ ...form, service_id: e.target.value })}>
                    <option value="">Mọi dịch vụ</option>
                    {services.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                  </select>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '12px' }}>
                  <div className="form-group">
                    <label>Số buổi *</label>
                    <input className="form-control" type="number" min="1" value={form.total_sessions}
                      onChange={(e) => setForm({ ...form, total_sessions: e.target.value })} required />
                  </div>
                  <div className="form-group">
                    <label>Giá gói (VNĐ) *</label>
                    <input className="form-control" type="number" min="0" step="10000" value={form.price}
                      onChange={(e) => setForm({ ...form, price: e.target.value })} required />
                  </div>
                  <div className="form-group">
                    <label>Hạn dùng (ngày)</label>
                    <input className="form-control" type="number" min="30" value={form.validity_days}
                      onChange={(e) => setForm({ ...form, validity_days: e.target.value })} />
                  </div>
                </div>
                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '14px', cursor: 'pointer' }}>
                  <input type="checkbox" checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} />
                  Đang mở bán
                </label>
              </div>
              <div className="modal-footer">
                <button type="button" className="btn btn-secondary" onClick={() => setShowModal(false)}>Hủy</button>
                <button type="submit" className="btn btn-primary">{editing ? 'Lưu' : 'Tạo gói'}</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Sell modal */}
      {showSellModal && (
        <div className="modal-overlay" onClick={() => setShowSellModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Bán gói cho khách hàng</h3>
              <button className="modal-close-btn" onClick={() => setShowSellModal(false)}>&times;</button>
            </div>
            <form onSubmit={handleSell}>
              <div className="modal-body">
                <div className="form-group">
                  <label>Khách hàng *</label>
                  <select className="form-control" value={sellForm.patient_id}
                    onChange={(e) => setSellForm({ ...sellForm, patient_id: e.target.value })} required>
                    {patients.map(p => <option key={p.id} value={p.id}>{p.full_name} {p.phone ? `(${p.phone})` : ''}</option>)}
                  </select>
                </div>
                <div className="form-group" style={{ marginBottom: 0 }}>
                  <label>Gói *</label>
                  <select className="form-control" value={sellForm.package_id}
                    onChange={(e) => setSellForm({ ...sellForm, package_id: e.target.value })} required>
                    {packages.filter(p => p.active).map(p => (
                      <option key={p.id} value={p.id}>{p.name} — {fmtMoney(p.price)} ({p.total_sessions} buổi)</option>
                    ))}
                  </select>
                </div>
              </div>
              <div className="modal-footer">
                <button type="button" className="btn btn-secondary" onClick={() => setShowSellModal(false)}>Hủy</button>
                <button type="submit" className="btn btn-primary">Xác nhận bán gói</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
