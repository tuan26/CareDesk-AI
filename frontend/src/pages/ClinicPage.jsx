import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { API_BASE } from '../api';

export default function ClinicPage() {
  const [clinic, setClinic] = useState(null);
  const [clinicForm, setClinicForm] = useState(null);
  const [branches, setBranches] = useState([]);
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [showBranchModal, setShowBranchModal] = useState(false);
  const [branchForm, setBranchForm] = useState({ name: '', address: '', phone: '', working_hours: '' });
  const navigate = useNavigate();

  const getHeaders = () => {
    const token = localStorage.getItem('caredesk_token');
    return {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    };
  };

  const isManager = user && (user.role === 'owner' || user.role === 'admin');

  const fetchData = async () => {
    try {
      const headers = getHeaders();
      const [meRes, clinicsRes, branchesRes] = await Promise.all([
        fetch(`${API_BASE}/auth/me`, { headers }),
        fetch(`${API_BASE}/clinic`, { headers }),
        fetch(`${API_BASE}/clinic/branches`, { headers })
      ]);
      if (meRes.status === 401 || clinicsRes.status === 401) throw new Error('Unauthorized');

      const me = await meRes.json();
      const clinics = await clinicsRes.json();
      const branchList = await branchesRes.json();

      setUser(me);
      const mainClinic = clinics[0] || null;
      setClinic(mainClinic);
      setClinicForm(mainClinic ? {
        name: mainClinic.name || '',
        logo_url: mainClinic.logo_url || '',
        phone: mainClinic.phone || '',
        address: mainClinic.address || '',
        cancellation_policy: mainClinic.cancellation_policy || ''
      } : null);
      setBranches(branchList);
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

  useEffect(() => {
    fetchData();
  }, [navigate]);

  const handleSaveClinic = async (e) => {
    e.preventDefault();
    if (!clinic) return;
    setSaving(true);
    try {
      const response = await fetch(`${API_BASE}/clinic/${clinic.id}`, {
        method: 'PUT',
        headers: getHeaders(),
        body: JSON.stringify(clinicForm)
      });
      if (response.ok) {
        const updated = await response.json();
        setClinic(updated);
        alert('Đã lưu thông tin phòng khám thành công!');
      } else {
        const data = await response.json().catch(() => null);
        alert(data?.detail || 'Không thể lưu thông tin phòng khám.');
      }
    } catch (err) {
      console.error(err);
      alert('Lỗi kết nối máy chủ.');
    } finally {
      setSaving(false);
    }
  };

  const handleAddBranch = async (e) => {
    e.preventDefault();
    if (!clinic) return;
    try {
      const response = await fetch(`${API_BASE}/clinic/branches`, {
        method: 'POST',
        headers: getHeaders(),
        body: JSON.stringify({ ...branchForm, clinic_id: clinic.id })
      });
      if (response.ok) {
        setShowBranchModal(false);
        setBranchForm({ name: '', address: '', phone: '', working_hours: '' });
        fetchData();
      } else {
        const data = await response.json().catch(() => null);
        alert(data?.detail || 'Không thể thêm chi nhánh.');
      }
    } catch (err) {
      console.error(err);
      alert('Lỗi kết nối máy chủ.');
    }
  };

  const handleDeleteBranch = async (branch) => {
    if (!window.confirm(`Bạn có chắc muốn xóa chi nhánh "${branch.name}"?`)) return;
    try {
      const response = await fetch(`${API_BASE}/clinic/branches/${branch.id}`, {
        method: 'DELETE',
        headers: getHeaders()
      });
      if (response.ok || response.status === 204) {
        fetchData();
      } else {
        const data = await response.json().catch(() => null);
        alert(data?.detail || 'Không thể xóa chi nhánh.');
      }
    } catch (err) {
      console.error(err);
      alert('Lỗi kết nối máy chủ.');
    }
  };

  if (loading) return <div style={{ padding: '24px', textAlign: 'center' }}>Đang tải thông tin phòng khám...</div>;

  return (
    <div>
      <div className="page-header">
        <div className="page-title">
          <h1>Thông tin Phòng khám</h1>
          <p>Quản lý hồ sơ phòng khám, chính sách hủy lịch và danh sách chi nhánh.</p>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.2fr', gap: '24px', alignItems: 'start' }}>

        {/* Panel Trái: Hồ sơ phòng khám */}
        <div className="card-table-wrapper">
          <div className="card-header">
            <h2>Hồ sơ phòng khám</h2>
            {!isManager && <span className="badge pending" style={{ fontSize: '10px' }}>CHỈ XEM</span>}
          </div>
          {clinicForm ? (
            <form onSubmit={handleSaveClinic} style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label>Tên phòng khám</label>
                <input
                  className="form-control"
                  value={clinicForm.name}
                  onChange={(e) => setClinicForm({ ...clinicForm, name: e.target.value })}
                  disabled={!isManager}
                  required
                />
              </div>
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label>Số điện thoại (Hotline)</label>
                <input
                  className="form-control"
                  value={clinicForm.phone}
                  onChange={(e) => setClinicForm({ ...clinicForm, phone: e.target.value })}
                  disabled={!isManager}
                />
              </div>
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label>Địa chỉ trụ sở</label>
                <input
                  className="form-control"
                  value={clinicForm.address}
                  onChange={(e) => setClinicForm({ ...clinicForm, address: e.target.value })}
                  disabled={!isManager}
                />
              </div>
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label>Logo URL</label>
                <input
                  className="form-control"
                  value={clinicForm.logo_url}
                  onChange={(e) => setClinicForm({ ...clinicForm, logo_url: e.target.value })}
                  disabled={!isManager}
                />
              </div>
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label>Chính sách hủy / đổi lịch hẹn</label>
                <textarea
                  className="form-control"
                  rows={4}
                  style={{ resize: 'vertical' }}
                  value={clinicForm.cancellation_policy}
                  onChange={(e) => setClinicForm({ ...clinicForm, cancellation_policy: e.target.value })}
                  disabled={!isManager}
                />
              </div>
              {isManager && (
                <button type="submit" className="btn btn-primary" disabled={saving}>
                  {saving ? 'Đang lưu...' : 'Lưu thay đổi'}
                </button>
              )}
            </form>
          ) : (
            <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)' }}>
              Chưa có dữ liệu phòng khám. Vui lòng khởi động backend để seed dữ liệu mẫu.
            </div>
          )}
        </div>

        {/* Panel Phải: Danh sách chi nhánh */}
        <div className="card-table-wrapper">
          <div className="card-header">
            <h2>Chi nhánh ({branches.length})</h2>
            {isManager && (
              <button className="btn btn-primary btn-sm" onClick={() => setShowBranchModal(true)}>
                + Thêm chi nhánh
              </button>
            )}
          </div>
          {branches.length === 0 ? (
            <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)' }}>Chưa có chi nhánh nào.</div>
          ) : (
            <table className="custom-table">
              <thead>
                <tr>
                  <th>Chi nhánh</th>
                  <th>Liên hệ</th>
                  <th>Giờ làm việc</th>
                  {isManager && <th style={{ width: '80px' }}></th>}
                </tr>
              </thead>
              <tbody>
                {branches.map((branch) => (
                  <tr key={branch.id}>
                    <td>
                      <div style={{ fontWeight: 600 }}>{branch.name}</div>
                      <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '2px' }}>{branch.address}</div>
                    </td>
                    <td>{branch.phone || '—'}</td>
                    <td>{branch.working_hours || '—'}</td>
                    {isManager && (
                      <td>
                        <button className="btn btn-danger btn-sm" onClick={() => handleDeleteBranch(branch)}>Xóa</button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Modal Thêm chi nhánh */}
      {showBranchModal && (
        <div className="modal-overlay" onClick={() => setShowBranchModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Thêm chi nhánh mới</h3>
              <button className="modal-close-btn" onClick={() => setShowBranchModal(false)}>&times;</button>
            </div>
            <form onSubmit={handleAddBranch}>
              <div className="modal-body">
                <div className="form-group">
                  <label>Tên chi nhánh *</label>
                  <input
                    className="form-control"
                    value={branchForm.name}
                    onChange={(e) => setBranchForm({ ...branchForm, name: e.target.value })}
                    placeholder="Chi nhánh Quận 3"
                    required
                  />
                </div>
                <div className="form-group">
                  <label>Địa chỉ *</label>
                  <input
                    className="form-control"
                    value={branchForm.address}
                    onChange={(e) => setBranchForm({ ...branchForm, address: e.target.value })}
                    placeholder="789 Đường Võ Văn Tần, Quận 3, TP.HCM"
                    required
                  />
                </div>
                <div className="form-group">
                  <label>Số điện thoại</label>
                  <input
                    className="form-control"
                    value={branchForm.phone}
                    onChange={(e) => setBranchForm({ ...branchForm, phone: e.target.value })}
                    placeholder="0287300789"
                  />
                </div>
                <div className="form-group" style={{ marginBottom: 0 }}>
                  <label>Giờ làm việc</label>
                  <input
                    className="form-control"
                    value={branchForm.working_hours}
                    onChange={(e) => setBranchForm({ ...branchForm, working_hours: e.target.value })}
                    placeholder="08:00 - 20:00"
                  />
                </div>
              </div>
              <div className="modal-footer">
                <button type="button" className="btn btn-secondary" onClick={() => setShowBranchModal(false)}>Hủy</button>
                <button type="submit" className="btn btn-primary">Thêm chi nhánh</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
