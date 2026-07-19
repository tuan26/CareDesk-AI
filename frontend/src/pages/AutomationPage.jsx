import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { API_BASE, getAuthHeaders } from '../api';

const fmtDelay = (minutes) => {
  if (!minutes) return 'Ngay lập tức';
  if (minutes < 60) return `${minutes} phút`;
  if (minutes < 1440) return `${Math.round(minutes / 60)} giờ`;
  return `${Math.round(minutes / 1440)} ngày`;
};

export default function AutomationPage() {
  const [tab, setTab] = useState('rules'); // rules | actions | reviews | waitlist
  const [rules, setRules] = useState([]);
  const [actions, setActions] = useState([]);
  const [reviews, setReviews] = useState([]);
  const [waitlist, setWaitlist] = useState([]);
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [editRule, setEditRule] = useState(null);
  const [template, setTemplate] = useState('');
  const navigate = useNavigate();

  const isManager = user && (user.role === 'owner' || user.role === 'admin');

  const fetchData = async () => {
    try {
      const headers = getAuthHeaders();
      const meRes = await fetch(`${API_BASE}/auth/me`, { headers });
      if (meRes.status === 401) throw new Error('Unauthorized');
      setUser(await meRes.json());

      const [rulesRes, actionsRes, reviewsRes, wlRes] = await Promise.all([
        fetch(`${API_BASE}/automations/rules`, { headers }),
        fetch(`${API_BASE}/automations/actions`, { headers }),
        fetch(`${API_BASE}/automations/reviews`, { headers }),
        fetch(`${API_BASE}/automations/waitlist`, { headers })
      ]);
      setRules(await rulesRes.json());
      setActions(await actionsRes.json());
      setReviews(await reviewsRes.json());
      setWaitlist(await wlRes.json());
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

  const toggleRule = async (rule) => {
    const res = await fetch(`${API_BASE}/automations/rules/${rule.id}`, {
      method: 'PUT', headers: getAuthHeaders(), body: JSON.stringify({ enabled: !rule.enabled })
    });
    if (res.ok) fetchData();
    else alert((await res.json().catch(() => null))?.detail || 'Không thể cập nhật.');
  };

  const saveTemplate = async () => {
    const res = await fetch(`${API_BASE}/automations/rules/${editRule.id}`, {
      method: 'PUT', headers: getAuthHeaders(), body: JSON.stringify({ message_template: template })
    });
    if (res.ok) { setEditRule(null); fetchData(); }
    else alert('Không thể lưu nội dung.');
  };

  const removeWaitlist = async (id) => {
    if (!window.confirm('Gỡ khách khỏi danh sách chờ?')) return;
    await fetch(`${API_BASE}/automations/waitlist/${id}`, { method: 'DELETE', headers: getAuthHeaders() });
    fetchData();
  };

  const TabBtn = ({ id, label, count }) => (
    <button
      className="btn btn-sm"
      style={{
        borderRadius: 0,
        background: tab === id ? 'var(--primary-color)' : 'white',
        color: tab === id ? 'white' : 'var(--text-main)'
      }}
      onClick={() => setTab(id)}
    >
      {label}{count != null ? ` (${count})` : ''}
    </button>
  );

  if (loading) return <div style={{ padding: '24px', textAlign: 'center' }}>Đang tải automation...</div>;

  return (
    <div>
      <div className="page-header">
        <div className="page-title">
          <h1>Automation doanh thu</h1>
          <p>AI tự follow-up khách hỏi giá, nhắc tái khám, đánh thức khách cũ, xin review và lấp chỗ trống — không cần nhân viên.</p>
        </div>
        <div style={{ display: 'flex', border: '1px solid var(--border-color)', borderRadius: '8px', overflow: 'hidden' }}>
          <TabBtn id="rules" label="⚙️ Kịch bản" count={rules.length} />
          <TabBtn id="actions" label="📤 Nhật ký gửi" count={actions.length} />
          <TabBtn id="reviews" label="⭐ Đánh giá" count={reviews.length} />
          <TabBtn id="waitlist" label="⏳ DS chờ" count={waitlist.length} />
        </div>
      </div>

      {tab === 'rules' && (
        <div className="card-table-wrapper">
          <div className="card-header"><h2>Kịch bản tự động</h2></div>
          <table className="custom-table">
            <thead>
              <tr><th>Kịch bản</th><th>Kích hoạt khi</th><th>Chờ</th><th>Đã gửi</th><th>Trạng thái</th>{isManager && <th style={{ width: '150px' }}></th>}</tr>
            </thead>
            <tbody>
              {rules.map((rule) => (
                <tr key={rule.id}>
                  <td style={{ maxWidth: '300px' }}>
                    <div style={{ fontWeight: 600 }}>{rule.name}</div>
                    {rule.message_template && (
                      <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        "{rule.message_template}"
                      </div>
                    )}
                  </td>
                  <td>{rule.trigger_label}</td>
                  <td>{fmtDelay(rule.delay_minutes)}</td>
                  <td><span className="badge confirmed">{rule.sent_count}</span></td>
                  <td>
                    <span className={`badge ${rule.enabled ? 'completed' : 'cancelled'}`}>
                      {rule.enabled ? 'Đang chạy' : 'Tắt'}
                    </span>
                  </td>
                  {isManager && (
                    <td>
                      <div style={{ display: 'flex', gap: '6px' }}>
                        <button className="btn btn-secondary btn-sm" onClick={() => toggleRule(rule)}>
                          {rule.enabled ? 'Tắt' : 'Bật'}
                        </button>
                        {rule.action_type === 'send_message' && (
                          <button className="btn btn-secondary btn-sm"
                            onClick={() => { setEditRule(rule); setTemplate(rule.message_template || ''); }}>
                            Sửa tin
                          </button>
                        )}
                      </div>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === 'actions' && (
        <div className="card-table-wrapper">
          <div className="card-header"><h2>Nhật ký automation</h2></div>
          {actions.length === 0 ? (
            <div style={{ padding: '28px', textAlign: 'center', color: 'var(--text-muted)' }}>Chưa có hành động nào được lên lịch.</div>
          ) : (
            <table className="custom-table">
              <thead><tr><th>Kịch bản</th><th>Khách hàng</th><th>Lịch gửi</th><th>Trạng thái</th></tr></thead>
              <tbody>
                {actions.map((a) => (
                  <tr key={a.id}>
                    <td>{a.rule_name}</td>
                    <td style={{ fontWeight: 600 }}>{a.patient_name}</td>
                    <td style={{ fontSize: '13px' }}>{new Date(a.due_at).toLocaleString('vi-VN')}</td>
                    <td>
                      <span className={`badge ${a.status === 'sent' ? 'completed' : a.status === 'pending' ? 'pending' : 'cancelled'}`}>
                        {a.status === 'sent' ? 'Đã gửi' : a.status === 'pending' ? 'Chờ gửi' : a.status === 'cancelled' ? 'Đã hủy (khách đã đặt)' : 'Lỗi'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {tab === 'reviews' && (
        <div className="card-table-wrapper">
          <div className="card-header"><h2>Đánh giá của khách (rating thấp được chặn trước khi lên mạng)</h2></div>
          {reviews.length === 0 ? (
            <div style={{ padding: '28px', textAlign: 'center', color: 'var(--text-muted)' }}>Chưa có đánh giá nào — automation sẽ tự hỏi khách sau mỗi buổi khám.</div>
          ) : (
            <table className="custom-table">
              <thead><tr><th>Khách hàng</th><th>Điểm</th><th>Phản hồi</th><th>Trạng thái</th><th>Thời gian</th></tr></thead>
              <tbody>
                {reviews.map((rv) => (
                  <tr key={rv.id} style={rv.status === 'escalated' ? { background: '#fef2f2' } : {}}>
                    <td>
                      <div style={{ fontWeight: 600 }}>{rv.patient_name}</div>
                      <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{rv.patient_phone}</div>
                    </td>
                    <td style={{ fontSize: '15px' }}>{rv.rating ? '⭐'.repeat(rv.rating) : '—'}</td>
                    <td style={{ fontSize: '13px', maxWidth: '260px' }}>{rv.feedback || '—'}</td>
                    <td>
                      <span className={`badge ${rv.status === 'answered' ? 'completed' : rv.status === 'escalated' ? 'cancelled' : 'pending'}`}>
                        {rv.status === 'answered' ? 'Hài lòng' : rv.status === 'escalated' ? '🚨 Cần xử lý gấp' : 'Chờ trả lời'}
                      </span>
                    </td>
                    <td style={{ fontSize: '12px' }}>{new Date(rv.sent_at).toLocaleString('vi-VN')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {tab === 'waitlist' && (
        <div className="card-table-wrapper">
          <div className="card-header"><h2>Danh sách chờ (tự động báo khi trống chỗ)</h2></div>
          {waitlist.length === 0 ? (
            <div style={{ padding: '28px', textAlign: 'center', color: 'var(--text-muted)' }}>
              Danh sách chờ trống. Khi khách muốn giờ đã kín, AI sẽ tự mời họ vào đây — có ca hủy là báo ngay.
            </div>
          ) : (
            <table className="custom-table">
              <thead><tr><th>Khách hàng</th><th>Dịch vụ</th><th>Ngày mong muốn</th><th>Trạng thái</th><th style={{ width: '80px' }}></th></tr></thead>
              <tbody>
                {waitlist.map((w) => (
                  <tr key={w.id}>
                    <td>
                      <div style={{ fontWeight: 600 }}>{w.patient_name}</div>
                      <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{w.patient_phone}</div>
                    </td>
                    <td>{w.service_name}</td>
                    <td>{w.preferred_date || 'Bất kỳ'}</td>
                    <td>
                      <span className={`badge ${w.status === 'notified' ? 'confirmed' : 'pending'}`}>
                        {w.status === 'notified' ? 'Đã báo trống chỗ' : 'Đang chờ'}
                      </span>
                    </td>
                    <td><button className="btn btn-danger btn-sm" onClick={() => removeWaitlist(w.id)}>Gỡ</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Edit template modal */}
      {editRule && (
        <div className="modal-overlay" onClick={() => setEditRule(null)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Sửa nội dung: {editRule.name}</h3>
              <button className="modal-close-btn" onClick={() => setEditRule(null)}>&times;</button>
            </div>
            <div className="modal-body">
              <div className="form-group" style={{ marginBottom: '8px' }}>
                <label>Nội dung tin nhắn</label>
                <textarea className="form-control" rows={5} style={{ resize: 'vertical' }}
                  value={template} onChange={(e) => setTemplate(e.target.value)} />
              </div>
              <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                Biến khả dụng: {'{name}'} = tên khách, {'{service}'} = dịch vụ, {'{clinic}'} = tên phòng khám, {'{phone}'} = hotline
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={() => setEditRule(null)}>Hủy</button>
              <button className="btn btn-primary" onClick={saveTemplate}>Lưu nội dung</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
