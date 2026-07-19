import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { API_BASE, getAuthHeaders } from '../api';

const STATUS_LABELS = {
  pending: 'Chờ xác nhận', confirmed: 'Đã xác nhận', completed: 'Hoàn thành',
  cancelled: 'Đã hủy', no_show: 'Vắng mặt'
};

const SOURCE_LABELS = { web: '🌐 Web', zalo: '💬 Zalo', facebook: '📘 Facebook' };

export default function PatientsPage() {
  const [patients, setPatients] = useState([]);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState(null); // patient detail in modal
  const [detailLoading, setDetailLoading] = useState(false);
  const [note, setNote] = useState('');
  const [tags, setTags] = useState([]);
  const [tagInput, setTagInput] = useState('');
  const [saving, setSaving] = useState(false);
  const navigate = useNavigate();

  const fetchPatients = async () => {
    try {
      const params = search ? `?search=${encodeURIComponent(search)}` : '';
      const res = await fetch(`${API_BASE}/appointments/patients${params}`, { headers: getAuthHeaders() });
      if (res.status === 401) {
        localStorage.removeItem('caredesk_token');
        navigate('/login');
        return;
      }
      setPatients(await res.json());
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const timer = setTimeout(fetchPatients, 300); // debounce search
    return () => clearTimeout(timer);
  }, [search]);

  const openDetail = async (patient) => {
    setDetailLoading(true);
    setDetail(null);
    try {
      const res = await fetch(`${API_BASE}/appointments/patients/${patient.id}`, { headers: getAuthHeaders() });
      if (res.ok) {
        const data = await res.json();
        setDetail(data);
        setNote(data.note || '');
        setTags(data.tags || []);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setDetailLoading(false);
    }
  };

  const handleSaveCrm = async () => {
    if (!detail) return;
    setSaving(true);
    try {
      const res = await fetch(`${API_BASE}/appointments/patients/${detail.id}`, {
        method: 'PUT',
        headers: getAuthHeaders(),
        body: JSON.stringify({ note, tags })
      });
      if (res.ok) {
        fetchPatients();
        alert('Đã lưu hồ sơ khách hàng.');
      } else {
        const data = await res.json().catch(() => null);
        alert(data?.detail || 'Không thể lưu.');
      }
    } catch (err) {
      console.error(err);
    } finally {
      setSaving(false);
    }
  };

  const addTag = () => {
    const t = tagInput.trim();
    if (t && !tags.includes(t)) setTags([...tags, t]);
    setTagInput('');
  };

  // Buổi thứ mấy của cùng một dịch vụ (theo dõi liệu trình nhiều buổi)
  const sessionNumber = (appt, allAppts) => {
    const sameService = allAppts
      .filter(a => a.service_id === appt.service_id && a.status !== 'cancelled')
      .sort((a, b) => new Date(a.start_time) - new Date(b.start_time));
    return sameService.findIndex(a => a.id === appt.id) + 1;
  };

  if (loading) return <div style={{ padding: '24px', textAlign: 'center' }}>Đang tải danh sách khách hàng...</div>;

  return (
    <div>
      <div className="page-header">
        <div className="page-title">
          <h1>Khách hàng (CRM)</h1>
          <p>Hồ sơ khách hàng từ mọi kênh: lịch sử hẹn, liệu trình, ghi chú và phân loại.</p>
        </div>
        <input
          className="form-control"
          style={{ width: '280px' }}
          placeholder="🔍 Tìm theo tên hoặc SĐT..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      <div className="card-table-wrapper">
        <div className="card-header">
          <h2>Danh sách khách hàng ({patients.length})</h2>
        </div>
        {patients.length === 0 ? (
          <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)' }}>Chưa có khách hàng nào.</div>
        ) : (
          <table className="custom-table">
            <thead>
              <tr>
                <th>Khách hàng</th>
                <th>Nguồn</th>
                <th>Phân loại (Tags)</th>
                <th>Consent</th>
                <th>Ngày tạo</th>
                <th style={{ width: '110px' }}></th>
              </tr>
            </thead>
            <tbody>
              {patients.map((p) => (
                <tr key={p.id}>
                  <td>
                    <div style={{ fontWeight: 600 }}>{p.full_name}</div>
                    <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{p.phone || '—'} {p.email ? `· ${p.email}` : ''}</div>
                  </td>
                  <td>{SOURCE_LABELS[p.source] || p.source}</td>
                  <td>
                    <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                      {(p.tags || []).length === 0 ? <span style={{ color: 'var(--text-muted)', fontSize: '12px' }}>—</span> :
                        p.tags.map((t) => <span key={t} className="badge confirmed" style={{ fontSize: '10px' }}>{t}</span>)}
                    </div>
                  </td>
                  <td>
                    <span className={`badge ${p.consent_given ? 'completed' : 'cancelled'}`} style={{ fontSize: '10px' }}>
                      {p.consent_given ? 'Đã đồng ý' : 'Chưa'}
                    </span>
                  </td>
                  <td style={{ fontSize: '13px' }}>{new Date(p.created_at).toLocaleDateString('vi-VN')}</td>
                  <td>
                    <button className="btn btn-secondary btn-sm" onClick={() => openDetail(p)}>Hồ sơ</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Modal hồ sơ khách */}
      {(detail || detailLoading) && (
        <div className="modal-overlay" onClick={() => setDetail(null)}>
          <div className="modal-content" style={{ width: '680px' }} onClick={(e) => e.stopPropagation()}>
            {detailLoading || !detail ? (
              <div style={{ padding: '40px', textAlign: 'center' }}>Đang tải hồ sơ...</div>
            ) : (
              <>
                <div className="modal-header">
                  <h3>Hồ sơ: {detail.full_name}</h3>
                  <button className="modal-close-btn" onClick={() => setDetail(null)}>&times;</button>
                </div>
                <div className="modal-body">
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '12px', marginBottom: '20px' }}>
                    <div style={{ padding: '10px', background: '#f8fafc', borderRadius: '8px', textAlign: 'center' }}>
                      <div style={{ fontSize: '10px', color: 'var(--text-muted)', fontWeight: 600 }}>SĐT</div>
                      <div style={{ fontWeight: 600, marginTop: '2px', fontSize: '13px' }}>{detail.phone || '—'}</div>
                    </div>
                    <div style={{ padding: '10px', background: '#f8fafc', borderRadius: '8px', textAlign: 'center' }}>
                      <div style={{ fontSize: '10px', color: 'var(--text-muted)', fontWeight: 600 }}>LỊCH HẸN</div>
                      <div style={{ fontWeight: 600, marginTop: '2px', fontSize: '13px' }}>{detail.appointments.length}</div>
                    </div>
                    <div style={{ padding: '10px', background: '#f8fafc', borderRadius: '8px', textAlign: 'center' }}>
                      <div style={{ fontSize: '10px', color: 'var(--text-muted)', fontWeight: 600 }}>HỘI THOẠI</div>
                      <div style={{ fontWeight: 600, marginTop: '2px', fontSize: '13px' }}>{detail.conversation_count}</div>
                    </div>
                  </div>

                  {detail.referral_code && (
                    <div style={{ padding: '10px 12px', background: 'var(--primary-light)', borderRadius: '8px', marginBottom: '16px', fontSize: '13px' }}>
                      🎁 Mã giới thiệu của khách: <b>{detail.referral_code}</b> — bạn bè nhập mã này khi đặt lịch sẽ được ưu đãi.
                    </div>
                  )}

                  {/* Tags */}
                  <div className="form-group">
                    <label>Phân loại (Tags)</label>
                    <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginBottom: '8px' }}>
                      {tags.map((t) => (
                        <span key={t} className="badge confirmed" style={{ cursor: 'pointer' }}
                          title="Bấm để xóa" onClick={() => setTags(tags.filter(x => x !== t))}>
                          {t} ✕
                        </span>
                      ))}
                    </div>
                    <div style={{ display: 'flex', gap: '8px' }}>
                      <input className="form-control" value={tagInput} placeholder="VIP, Liệu trình mụn, Khách laser..."
                        onChange={(e) => setTagInput(e.target.value)}
                        onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addTag(); } }} />
                      <button type="button" className="btn btn-secondary btn-sm" onClick={addTag}>Thêm</button>
                    </div>
                  </div>

                  {/* Note */}
                  <div className="form-group">
                    <label>Ghi chú nội bộ</label>
                    <textarea className="form-control" rows={3} style={{ resize: 'vertical' }}
                      value={note} onChange={(e) => setNote(e.target.value)}
                      placeholder="Da nhạy cảm, dị ứng AHA. Đang liệu trình trị mụn buổi 3/5..." />
                  </div>

                  {/* Appointment history with session tracking */}
                  <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, textTransform: 'uppercase', marginBottom: '8px' }}>
                    Lịch sử hẹn & liệu trình
                  </label>
                  {detail.appointments.length === 0 ? (
                    <div style={{ fontSize: '13px', color: 'var(--text-muted)' }}>Chưa có lịch hẹn nào.</div>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '220px', overflowY: 'auto' }}>
                      {detail.appointments.map((a) => (
                        <div key={a.id} style={{ border: '1px solid var(--border-color)', borderRadius: '8px', padding: '10px 12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <div>
                            <div style={{ fontSize: '13px', fontWeight: 600 }}>
                              {a.service?.name}
                              {a.status !== 'cancelled' && (
                                <span style={{ marginLeft: '8px', fontSize: '10px', color: 'var(--primary-color)', background: 'var(--primary-light)', padding: '2px 6px', borderRadius: '4px' }}>
                                  Buổi {sessionNumber(a, detail.appointments)}
                                </span>
                              )}
                            </div>
                            <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
                              {new Date(a.start_time).toLocaleString('vi-VN')} · {a.doctor?.name}
                            </div>
                          </div>
                          <span className={`badge ${a.status}`} style={{ fontSize: '10px' }}>{STATUS_LABELS[a.status] || a.status}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                <div className="modal-footer">
                  <button className="btn btn-secondary" onClick={() => setDetail(null)}>Đóng</button>
                  <button className="btn btn-primary" onClick={handleSaveCrm} disabled={saving}>
                    {saving ? 'Đang lưu...' : 'Lưu hồ sơ'}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
