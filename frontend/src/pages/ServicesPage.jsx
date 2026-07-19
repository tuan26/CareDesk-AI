import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { API_BASE } from '../api';

const EMPTY_FORM = {
  name: '',
  description: '',
  price: '',
  duration_minutes: 30,
  preparation_instructions: '',
  faq_data: []
};

export default function ServicesPage() {
  const [services, setServices] = useState([]);
  const [clinicId, setClinicId] = useState(null);
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [editingService, setEditingService] = useState(null); // null = create mode
  const [form, setForm] = useState(EMPTY_FORM);
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
      const [meRes, servicesRes, clinicsRes] = await Promise.all([
        fetch(`${API_BASE}/auth/me`, { headers }),
        fetch(`${API_BASE}/clinic/services`, { headers }),
        fetch(`${API_BASE}/clinic`, { headers })
      ]);
      if (meRes.status === 401 || servicesRes.status === 401) throw new Error('Unauthorized');

      setUser(await meRes.json());
      setServices(await servicesRes.json());
      const clinics = await clinicsRes.json();
      if (clinics.length > 0) setClinicId(clinics[0].id);
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

  const openCreateModal = () => {
    setEditingService(null);
    setForm(EMPTY_FORM);
    setShowModal(true);
  };

  const openEditModal = (service) => {
    setEditingService(service);
    setForm({
      name: service.name,
      description: service.description || '',
      price: service.price,
      duration_minutes: service.duration_minutes,
      preparation_instructions: service.preparation_instructions || '',
      faq_data: service.faq_data ? [...service.faq_data] : []
    });
    setShowModal(true);
  };

  const handleFaqChange = (index, field, value) => {
    const updated = [...form.faq_data];
    updated[index] = { ...updated[index], [field]: value };
    setForm({ ...form, faq_data: updated });
  };

  const addFaqRow = () => {
    setForm({ ...form, faq_data: [...form.faq_data, { question: '', answer: '' }] });
  };

  const removeFaqRow = (index) => {
    setForm({ ...form, faq_data: form.faq_data.filter((_, i) => i !== index) });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!clinicId) {
      alert('Chưa có dữ liệu phòng khám để gắn dịch vụ.');
      return;
    }

    const payload = {
      clinic_id: clinicId,
      name: form.name,
      description: form.description || null,
      price: parseFloat(form.price) || 0,
      duration_minutes: parseInt(form.duration_minutes, 10) || 30,
      preparation_instructions: form.preparation_instructions || null,
      faq_data: form.faq_data.filter(f => f.question.trim() && f.answer.trim())
    };

    const url = editingService
      ? `${API_BASE}/clinic/services/${editingService.id}`
      : `${API_BASE}/clinic/services`;

    try {
      const response = await fetch(url, {
        method: editingService ? 'PUT' : 'POST',
        headers: getHeaders(),
        body: JSON.stringify(payload)
      });
      if (response.ok) {
        setShowModal(false);
        fetchData();
      } else {
        const data = await response.json().catch(() => null);
        alert(data?.detail || 'Không thể lưu dịch vụ.');
      }
    } catch (err) {
      console.error(err);
      alert('Lỗi kết nối máy chủ.');
    }
  };

  const handleDelete = async (service) => {
    if (!window.confirm(`Bạn có chắc muốn xóa dịch vụ "${service.name}"?\nCác lịch hẹn gắn với dịch vụ này cũng sẽ bị xóa.`)) return;
    try {
      const response = await fetch(`${API_BASE}/clinic/services/${service.id}`, {
        method: 'DELETE',
        headers: getHeaders()
      });
      if (response.ok || response.status === 204) {
        fetchData();
      } else {
        const data = await response.json().catch(() => null);
        alert(data?.detail || 'Không thể xóa dịch vụ.');
      }
    } catch (err) {
      console.error(err);
      alert('Lỗi kết nối máy chủ.');
    }
  };

  const formatPrice = (price) => new Intl.NumberFormat('vi-VN').format(price) + 'đ';

  if (loading) return <div style={{ padding: '24px', textAlign: 'center' }}>Đang tải danh sách dịch vụ...</div>;

  return (
    <div>
      <div className="page-header">
        <div className="page-title">
          <h1>Dịch vụ & Bảng giá</h1>
          <p>Quản lý dịch vụ khám chữa bệnh. AI sử dụng dữ liệu này để tư vấn giá và FAQ cho khách hàng.</p>
        </div>
        {isManager && (
          <button className="btn btn-primary" onClick={openCreateModal}>+ Thêm dịch vụ</button>
        )}
      </div>

      <div className="card-table-wrapper">
        <div className="card-header">
          <h2>Danh sách dịch vụ ({services.length})</h2>
        </div>
        {services.length === 0 ? (
          <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)' }}>Chưa có dịch vụ nào.</div>
        ) : (
          <table className="custom-table">
            <thead>
              <tr>
                <th>Dịch vụ</th>
                <th>Giá niêm yết</th>
                <th>Thời lượng</th>
                <th>FAQ cho AI</th>
                {isManager && <th style={{ width: '140px' }}>Thao tác</th>}
              </tr>
            </thead>
            <tbody>
              {services.map((service) => (
                <tr key={service.id}>
                  <td style={{ maxWidth: '380px' }}>
                    <div style={{ fontWeight: 600 }}>{service.name}</div>
                    {service.description && (
                      <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '2px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {service.description}
                      </div>
                    )}
                  </td>
                  <td style={{ fontWeight: 600, color: 'var(--primary-color)' }}>{formatPrice(service.price)}</td>
                  <td>{service.duration_minutes} phút</td>
                  <td>
                    <span className={`badge ${service.faq_data?.length ? 'completed' : 'no_show'}`}>
                      {service.faq_data?.length || 0} câu hỏi
                    </span>
                  </td>
                  {isManager && (
                    <td>
                      <div style={{ display: 'flex', gap: '8px' }}>
                        <button className="btn btn-secondary btn-sm" onClick={() => openEditModal(service)}>Sửa</button>
                        <button className="btn btn-danger btn-sm" onClick={() => handleDelete(service)}>Xóa</button>
                      </div>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Modal Thêm/Sửa dịch vụ */}
      {showModal && (
        <div className="modal-overlay" onClick={() => setShowModal(false)}>
          <div className="modal-content" style={{ width: '640px' }} onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>{editingService ? 'Chỉnh sửa dịch vụ' : 'Thêm dịch vụ mới'}</h3>
              <button className="modal-close-btn" onClick={() => setShowModal(false)}>&times;</button>
            </div>
            <form onSubmit={handleSubmit}>
              <div className="modal-body">
                <div className="form-group">
                  <label>Tên dịch vụ *</label>
                  <input
                    className="form-control"
                    value={form.name}
                    onChange={(e) => setForm({ ...form, name: e.target.value })}
                    placeholder="Điều trị mụn Chuẩn Y Khoa"
                    required
                  />
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                  <div className="form-group">
                    <label>Giá (VNĐ) *</label>
                    <input
                      className="form-control"
                      type="number"
                      min="0"
                      step="1000"
                      value={form.price}
                      onChange={(e) => setForm({ ...form, price: e.target.value })}
                      placeholder="450000"
                      required
                    />
                  </div>
                  <div className="form-group">
                    <label>Thời lượng (phút) *</label>
                    <input
                      className="form-control"
                      type="number"
                      min="5"
                      step="5"
                      value={form.duration_minutes}
                      onChange={(e) => setForm({ ...form, duration_minutes: e.target.value })}
                      required
                    />
                  </div>
                </div>
                <div className="form-group">
                  <label>Mô tả dịch vụ</label>
                  <textarea
                    className="form-control"
                    rows={3}
                    style={{ resize: 'vertical' }}
                    value={form.description}
                    onChange={(e) => setForm({ ...form, description: e.target.value })}
                    placeholder="Mô tả quy trình, công nghệ sử dụng..."
                  />
                </div>
                <div className="form-group">
                  <label>Hướng dẫn chuẩn bị trước khám</label>
                  <textarea
                    className="form-control"
                    rows={2}
                    style={{ resize: 'vertical' }}
                    value={form.preparation_instructions}
                    onChange={(e) => setForm({ ...form, preparation_instructions: e.target.value })}
                    placeholder="Ví dụ: Tẩy trang sạch trước giờ khám 10 phút..."
                  />
                </div>

                {/* FAQ Editor */}
                <div className="form-group" style={{ marginBottom: 0 }}>
                  <label>FAQ cho AI tư vấn (Hỏi - Đáp)</label>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                    {form.faq_data.map((faq, index) => (
                      <div key={index} style={{ border: '1px solid var(--border-color)', borderRadius: '8px', padding: '12px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                          <input
                            className="form-control"
                            value={faq.question}
                            onChange={(e) => handleFaqChange(index, 'question', e.target.value)}
                            placeholder={`Câu hỏi #${index + 1}`}
                          />
                          <button type="button" className="btn btn-danger btn-sm" onClick={() => removeFaqRow(index)}>Xóa</button>
                        </div>
                        <textarea
                          className="form-control"
                          rows={2}
                          style={{ resize: 'vertical' }}
                          value={faq.answer}
                          onChange={(e) => handleFaqChange(index, 'answer', e.target.value)}
                          placeholder="Câu trả lời AI sẽ dùng để tư vấn..."
                        />
                      </div>
                    ))}
                    <button type="button" className="btn btn-secondary btn-sm" style={{ alignSelf: 'flex-start' }} onClick={addFaqRow}>
                      + Thêm câu hỏi FAQ
                    </button>
                  </div>
                </div>
              </div>
              <div className="modal-footer">
                <button type="button" className="btn btn-secondary" onClick={() => setShowModal(false)}>Hủy</button>
                <button type="submit" className="btn btn-primary">{editingService ? 'Lưu thay đổi' : 'Thêm dịch vụ'}</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
