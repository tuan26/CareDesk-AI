import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { API_BASE, getAuthHeaders } from '../api';

const API_HOST = API_BASE.replace('/api/v1', '');

function ChannelCard({ channel, title, description, integration, clinicId, onSave }) {
  const [enabled, setEnabled] = useState(integration?.enabled || false);
  const [token, setToken] = useState('');
  const [verifyToken, setVerifyToken] = useState(integration?.verify_token || '');
  const [extraConfig, setExtraConfig] = useState(integration?.extra_config || {});
  const [saving, setSaving] = useState(false);
  const webhookUrl = `${API_HOST}/api/v1/webhooks/${channel}/${clinicId || 1}`;

  useEffect(() => {
    setEnabled(integration?.enabled || false);
    setVerifyToken(integration?.verify_token || '');
    setExtraConfig(integration?.extra_config || {});
  }, [integration]);

  const setExtra = (key, value) => setExtraConfig(prev => ({ ...prev, [key]: value }));

  const save = async () => {
    setSaving(true);
    await onSave({
      channel,
      enabled,
      access_token: token || null,
      verify_token: verifyToken || null,
      extra_config: extraConfig
    });
    setToken('');
    setSaving(false);
  };

  return (
    <div style={{ border: '1px solid var(--border-color)', padding: '16px', borderRadius: '10px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
        <div>
          <div style={{ fontWeight: 600, fontSize: '14px' }}>{title}</div>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>{description}</div>
        </div>
        <span className={`badge ${integration?.enabled ? 'completed' : 'no_show'}`} style={{ fontSize: '10px' }}>
          {integration?.enabled ? 'ĐANG HOẠT ĐỘNG' : 'CHƯA KÍCH HOẠT'}
        </span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
          Webhook URL (dán vào cấu hình {channel === 'zalo' ? 'Zalo OA' : 'Facebook App'}):
          <code style={{ display: 'block', background: '#f8fafc', padding: '6px 8px', borderRadius: '6px', marginTop: '4px', fontSize: '11px', wordBreak: 'break-all' }}>{webhookUrl}</code>
        </div>
        <input className="form-control" type="password" placeholder={integration?.access_token_masked ? `Access Token (hiện tại: ${integration.access_token_masked})` : 'Access Token'}
          value={token} onChange={(e) => setToken(e.target.value)} style={{ fontSize: '12px' }} />
        {channel === 'facebook' && (
          <>
            <input className="form-control" placeholder="Verify Token (tự đặt, dùng khi xác thực webhook)"
              value={verifyToken} onChange={(e) => setVerifyToken(e.target.value)} style={{ fontSize: '12px' }} />
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
              <input className="form-control" placeholder="Pixel ID (CAPI)" style={{ fontSize: '12px' }}
                value={extraConfig.pixel_id || ''} onChange={(e) => setExtra('pixel_id', e.target.value)} />
              <input className="form-control" type="password" placeholder="CAPI Token" style={{ fontSize: '12px' }}
                value={extraConfig.capi_token || ''} onChange={(e) => setExtra('capi_token', e.target.value)} />
            </div>
            <div style={{ display: 'flex', gap: '16px' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '12px', cursor: 'pointer' }}>
                <input type="checkbox" checked={!!extraConfig.comment_guard}
                  onChange={(e) => setExtra('comment_guard', e.target.checked)} />
                Comment Guard (tự trả lời comment ads)
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '12px', cursor: 'pointer' }}>
                <input type="checkbox" checked={!!extraConfig.hide_comments}
                  onChange={(e) => setExtra('hide_comments', e.target.checked)} />
                Ẩn comment (chống cướp khách)
              </label>
            </div>
          </>
        )}
        {channel === 'zalo' && (
          <input className="form-control" placeholder="ZNS Template ID (nhắn tin nhắc lịch qua ZNS)" style={{ fontSize: '12px' }}
            value={extraConfig.zns_template_id || ''} onChange={(e) => setExtra('zns_template_id', e.target.value)} />
        )}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', cursor: 'pointer' }}>
            <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
            Kích hoạt kênh
          </label>
          <button className="btn btn-primary btn-sm" onClick={save} disabled={saving}>
            {saving ? 'Đang lưu...' : 'Lưu cấu hình'}
          </button>
        </div>
        <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
          * Chưa có token? Kênh vẫn chạy ở chế độ mock (log console) để bạn thử nghiệm webhook.
        </div>
      </div>
    </div>
  );
}

function RevenueConfigCard({ clinic, onSaved }) {
  const [deposit, setDeposit] = useState(clinic.deposit_amount || 0);
  const [reviewUrl, setReviewUrl] = useState(clinic.google_review_url || '');
  const [digest, setDigest] = useState(clinic.digest_enabled !== false);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      const res = await fetch(`${API_BASE}/clinic/${clinic.id}`, {
        method: 'PUT',
        headers: getAuthHeaders(),
        body: JSON.stringify({
          name: clinic.name,
          deposit_amount: parseFloat(deposit) || 0,
          google_review_url: reviewUrl || null,
          digest_enabled: digest
        })
      });
      if (res.ok) {
        alert('Đã lưu cấu hình Revenue Engine.');
        onSaved();
      } else {
        alert((await res.json().catch(() => null))?.detail || 'Không thể lưu.');
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="card-table-wrapper" style={{ height: 'fit-content' }}>
      <div className="card-header"><h2>💰 Cấu hình Revenue Engine</h2></div>
      <div style={{ padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
        <div className="form-group" style={{ marginBottom: 0 }}>
          <label>Tiền cọc giữ chỗ (VNĐ) — 0 = tắt đặt cọc</label>
          <input className="form-control" type="number" min="0" step="50000"
            value={deposit} onChange={(e) => setDeposit(e.target.value)} />
          <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
            Khi bật, AI yêu cầu khách đặt cọc khi chốt lịch — lịch tự XÁC NHẬN khi thanh toán xong (giảm no-show mạnh nhất).
          </div>
        </div>
        <div className="form-group" style={{ marginBottom: 0 }}>
          <label>Link Google Review</label>
          <input className="form-control" placeholder="https://g.page/r/..../review"
            value={reviewUrl} onChange={(e) => setReviewUrl(e.target.value)} />
          <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
            Khách chấm 4-5 sao được mời để lại review Google. Khách chấm thấp bị chặn lại và báo bạn xử lý riêng.
          </div>
        </div>
        <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', cursor: 'pointer' }}>
          <input type="checkbox" checked={digest} onChange={(e) => setDigest(e.target.checked)} />
          Nhận bản tin vận hành 8h & 20h hằng ngày (SMS/ZNS + email)
        </label>
        <button className="btn btn-primary btn-sm" style={{ alignSelf: 'flex-start' }} onClick={save} disabled={saving}>
          {saving ? 'Đang lưu...' : 'Lưu cấu hình'}
        </button>
      </div>
    </div>
  );
}

export default function SettingsPage() {
  const [user, setUser] = useState(null);
  const [clinic, setClinic] = useState(null);
  const [channels, setChannels] = useState([]);
  const [auditLogs, setAuditLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [evalLoading, setEvalLoading] = useState(false);
  const [evalReport, setEvalReport] = useState(null);
  const navigate = useNavigate();

  const isManager = user && (user.role === 'owner' || user.role === 'admin');

  const fetchData = async () => {
    try {
      const headers = getAuthHeaders();
      const meRes = await fetch(`${API_BASE}/auth/me`, { headers });
      if (meRes.status === 401) throw new Error('Unauthorized');
      const me = await meRes.json();
      setUser(me);

      const clinicsRes = await fetch(`${API_BASE}/clinic`, { headers });
      const clinics = await clinicsRes.json();
      setClinic(clinics[0] || null);

      if (me.role === 'owner' || me.role === 'admin') {
        const [chRes, auditRes] = await Promise.all([
          fetch(`${API_BASE}/clinic/channels`, { headers }),
          fetch(`${API_BASE}/clinic/audit-logs?limit=50`, { headers })
        ]);
        if (chRes.ok) setChannels(await chRes.json());
        if (auditRes.ok) setAuditLogs(await auditRes.json());
      }
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

  const handleSaveChannel = async (payload) => {
    try {
      const res = await fetch(`${API_BASE}/clinic/channels`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        fetchData();
      } else {
        const data = await res.json().catch(() => null);
        alert(data?.detail || 'Không thể lưu cấu hình kênh.');
      }
    } catch (err) {
      console.error(err);
      alert('Lỗi kết nối máy chủ.');
    }
  };

  const handleRunEvaluation = async () => {
    setEvalLoading(true);
    setEvalReport(null);
    try {
      const response = await fetch(`${API_BASE}/chat/evaluate-ai`, {
        method: 'POST',
        headers: getAuthHeaders()
      });
      if (response.ok) {
        setEvalReport(await response.json());
      } else {
        alert('Lỗi chạy đánh giá AI');
      }
    } catch (err) {
      console.error(err);
      alert('Không thể kết nối API đánh giá.');
    } finally {
      setEvalLoading(false);
    }
  };

  const getChannel = (name) => channels.find(c => c.channel === name);

  if (loading) return <div>Đang tải thông tin tài khoản...</div>;

  return (
    <div>
      <div className="page-header">
        <div className="page-title">
          <h1>Cài đặt hệ thống</h1>
          <p>Tài khoản, gói cước, kết nối kênh Zalo/Facebook, kiểm định AI và nhật ký hệ thống.</p>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.2fr', gap: '24px', alignItems: 'start' }}>

        {/* Panel Trái */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>

          {/* Tài khoản + Gói cước */}
          {user && (
            <div className="card-table-wrapper" style={{ height: 'fit-content' }}>
              <div className="card-header">
                <h2>Tài khoản & Gói cước</h2>
              </div>
              <div style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <div>
                    <div style={{ fontWeight: 600, fontSize: '15px', color: 'var(--dark-color)' }}>{user.full_name}</div>
                    <div style={{ fontSize: '13px', color: 'var(--text-muted)' }}>{user.email}</div>
                  </div>
                  <span className="badge confirmed" style={{ height: 'fit-content' }}>{user.role.toUpperCase()}</span>
                </div>
                {clinic && (
                  <div style={{ borderTop: '1px solid var(--border-color)', paddingTop: '14px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <div>
                        <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Phòng khám</div>
                        <div style={{ fontWeight: 600, fontSize: '14px' }}>{clinic.name}</div>
                      </div>
                      <span className={`badge ${clinic.plan === 'pro' ? 'completed' : 'pending'}`}>
                        GÓI {(clinic.plan || 'free').toUpperCase()}
                      </span>
                    </div>
                    <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '8px' }}>
                      Hạn mức AI: <b>{new Intl.NumberFormat('vi-VN').format(clinic.ai_quota_monthly)}</b> hội thoại bot/tháng.
                      {clinic.plan !== 'pro' && ' Nâng cấp Pro để tăng lên 5.000/tháng + kênh Zalo/FB.'}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Cấu hình Revenue Engine */}
          {isManager && clinic && (
            <RevenueConfigCard clinic={clinic} onSaved={fetchData} />
          )}

          {/* Kết nối kênh */}
          <div className="card-table-wrapper" style={{ height: 'fit-content' }}>
            <div className="card-header">
              <h2>Kết nối kênh CSKH</h2>
            </div>
            <div style={{ padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
              {isManager ? (
                <>
                  <ChannelCard
                    channel="zalo" title="Zalo Official Account"
                    description="Nhận tin nhắn Zalo OA, AI trả lời + gửi ZNS nhắc lịch"
                    integration={getChannel('zalo')} clinicId={user?.clinic_id} onSave={handleSaveChannel}
                  />
                  <ChannelCard
                    channel="facebook" title="Facebook Page Messenger"
                    description="Đồng bộ inbox fanpage, AI trực chat 24/7"
                    integration={getChannel('facebook')} clinicId={user?.clinic_id} onSave={handleSaveChannel}
                  />
                </>
              ) : (
                <div style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
                  Chỉ chủ phòng khám / admin được cấu hình kênh kết nối.
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Panel Phải */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>

          {/* Đánh giá AI */}
          <div className="card-table-wrapper" style={{ height: 'fit-content' }}>
            <div className="card-header">
              <h2>Kiểm định & Đánh giá Chất lượng AI</h2>
              <button
                className="btn btn-primary btn-sm"
                onClick={handleRunEvaluation}
                disabled={evalLoading}
              >
                {evalLoading ? 'Đang chạy test...' : '⚡ Chạy Đánh giá AI'}
              </button>
            </div>

            <div style={{ padding: '24px' }}>
              <p style={{ fontSize: '13px', color: 'var(--text-muted)', marginBottom: '16px', lineHeight: '1.5' }}>
                Hệ thống tự động chạy giả lập <b>7 kịch bản hội thoại mẫu</b> (Golden Dataset): hỏi giá, địa chỉ, giờ làm việc,
                kích hoạt đặt lịch và các câu hỏi rủi ro y tế (bắt buộc handoff) để chấm điểm độ chính xác của AI.
              </p>

              {evalReport ? (
                <div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '12px', marginBottom: '20px' }}>
                    <div style={{ padding: '12px', backgroundColor: '#f8fafc', border: '1px solid var(--border-color)', borderRadius: '8px', textAlign: 'center' }}>
                      <div style={{ fontSize: '10px', color: 'var(--text-muted)', fontWeight: 600 }}>TỔNG SỐ TEST</div>
                      <div style={{ fontSize: '20px', fontWeight: 700, color: 'var(--dark-color)', marginTop: '4px' }}>{evalReport.total_tests}</div>
                    </div>
                    <div style={{ padding: '12px', backgroundColor: '#f8fafc', border: '1px solid var(--border-color)', borderRadius: '8px', textAlign: 'center' }}>
                      <div style={{ fontSize: '10px', color: 'var(--text-muted)', fontWeight: 600 }}>ĐẠT YÊU CẦU</div>
                      <div style={{ fontSize: '20px', fontWeight: 700, color: 'var(--success-color)', marginTop: '4px' }}>{evalReport.passed_tests}</div>
                    </div>
                    <div style={{ padding: '12px', backgroundColor: evalReport.accuracy_rate_percent >= 80 ? '#ecfdf5' : '#fff9e6', border: '1px solid ' + (evalReport.accuracy_rate_percent >= 80 ? 'rgba(16,185,129,0.2)' : 'rgba(245,158,11,0.2)'), borderRadius: '8px', textAlign: 'center' }}>
                      <div style={{ fontSize: '10px', color: evalReport.accuracy_rate_percent >= 80 ? 'var(--success-color)' : 'var(--warning-color)', fontWeight: 600 }}>TỶ LỆ CHÍNH XÁC</div>
                      <div style={{ fontSize: '20px', fontWeight: 700, color: evalReport.accuracy_rate_percent >= 80 ? 'var(--success-color)' : 'var(--warning-color)', marginTop: '4px' }}>
                        {evalReport.accuracy_rate_percent}%
                      </div>
                    </div>
                  </div>

                  <h4 style={{ fontSize: '13px', fontWeight: 600, color: 'var(--dark-color)', marginBottom: '10px' }}>Kết quả chi tiết kịch bản:</h4>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '300px', overflowY: 'auto' }}>
                    {evalReport.results.map((res) => (
                      <div
                        key={res.id}
                        style={{
                          border: '1px solid var(--border-color)', borderRadius: '6px', padding: '10px 12px',
                          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                          backgroundColor: res.passed ? '#fcfdfd' : '#fef2f2'
                        }}
                      >
                        <div>
                          <div style={{ fontSize: '13px', fontWeight: 600 }}>Case #{res.id}: {res.description}</div>
                          <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
                            <span>Handoff: {res.actual_handoff ? 'Có' : 'Không'} (Mong đợi: {res.expected_handoff ? 'Có' : 'Không'})</span>
                            <span style={{ marginLeft: '12px' }}>Điểm từ khóa: {res.keyword_score}%</span>
                          </div>
                        </div>
                        <span className={`badge ${res.passed ? 'completed' : 'cancelled'}`} style={{ fontSize: '10px', padding: '2px 8px' }}>
                          {res.passed ? 'ĐẠT' : 'LỖI'}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <div style={{ border: '1px dashed var(--border-color)', borderRadius: '8px', padding: '32px', textAlign: 'center', color: 'var(--text-muted)' }}>
                  Bấm nút "Chạy Đánh giá AI" để bắt đầu kiểm định tự động.
                </div>
              )}
            </div>
          </div>

          {/* Audit Log */}
          {isManager && (
            <div className="card-table-wrapper" style={{ height: 'fit-content' }}>
              <div className="card-header">
                <h2>Nhật ký hệ thống (Audit Log)</h2>
              </div>
              {auditLogs.length === 0 ? (
                <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '13px' }}>Chưa có hoạt động nào được ghi nhận.</div>
              ) : (
                <div style={{ maxHeight: '320px', overflowY: 'auto' }}>
                  <table className="custom-table">
                    <thead>
                      <tr><th>Thời gian</th><th>Người thực hiện</th><th>Hành động</th></tr>
                    </thead>
                    <tbody>
                      {auditLogs.map((log) => (
                        <tr key={log.id}>
                          <td style={{ fontSize: '12px', whiteSpace: 'nowrap' }}>{new Date(log.created_at).toLocaleString('vi-VN')}</td>
                          <td style={{ fontSize: '12px' }}>{log.user_name || 'Hệ thống'}</td>
                          <td style={{ fontSize: '12px' }}>
                            <div style={{ fontWeight: 600 }}>{log.action}</div>
                            <div style={{ color: 'var(--text-muted)' }}>{log.details}</div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
