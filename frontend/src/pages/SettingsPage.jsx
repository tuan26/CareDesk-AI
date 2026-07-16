import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

export default function SettingsPage() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [evalLoading, setEvalLoading] = useState(false);
  const [evalReport, setEvalReport] = useState(null);
  const navigate = useNavigate();

  const getHeaders = () => {
    const token = localStorage.getItem('caredesk_token');
    return {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    };
  };

  const fetchUserInfo = async () => {
    try {
      const response = await fetch('http://localhost:8000/api/v1/auth/me', {
        headers: getHeaders()
      });
      if (response.status === 401) throw new Error('Unauthorized');
      const data = await response.json();
      setUser(data);
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
    fetchUserInfo();
  }, [navigate]);

  const handleRunEvaluation = async () => {
    setEvalLoading(true);
    setEvalReport(null);
    try {
      const response = await fetch('http://localhost:8000/api/v1/chat/evaluate-ai', {
        method: 'POST',
        headers: getHeaders()
      });
      if (response.ok) {
        const report = await response.json();
        setEvalReport(report);
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

  if (loading) return <div>Đang tải thông tin tài khoản...</div>;

  return (
    <div>
      <div className="page-header">
        <div className="page-title">
          <h1>Cài đặt hệ thống</h1>
          <p>Quản lý tài khoản cá nhân, kết nối kênh Zalo/FB và chấm điểm đánh giá chất lượng AI.</p>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.2fr', gap: '24px' }}>
        
        {/* Panel Trái: Tài khoản & Kết nối Kênh */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          
          {/* Thông tin tài khoản */}
          {user && (
            <div className="card-table-wrapper" style={{ height: 'fit-content' }}>
              <div className="card-header">
                <h2>Thông tin cá nhân</h2>
              </div>
              <div style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
                <div>
                  <strong style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Họ và tên:</strong>
                  <div style={{ fontWeight: 600, fontSize: '15px', color: 'var(--dark-color)', marginTop: '2px' }}>{user.full_name}</div>
                </div>
                <div>
                  <strong style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Email đăng nhập:</strong>
                  <div style={{ marginTop: '2px' }}>{user.email}</div>
                </div>
                <div>
                  <strong style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Vai trò truy cập:</strong>
                  <div style={{ marginTop: '4px' }}>
                    <span className="badge confirmed">{user.role.toUpperCase()}</span>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Cấu hình kênh liên kết */}
          <div className="card-table-wrapper" style={{ height: 'fit-content' }}>
            <div className="card-header">
              <h2>Kết nối kênh CSKH</h2>
            </div>
            <div style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div style={{ border: '1px dashed var(--border-color)', padding: '16px', borderRadius: '8px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <div style={{ fontWeight: 600, fontSize: '14px' }}>Zalo OA Integration</div>
                  <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>Tự động tiếp nhận tin nhắn từ Zalo Official Account</div>
                </div>
                <span className="badge pending" style={{ fontSize: '11px' }}>SẮP RA MẮT (PRO)</span>
              </div>

              <div style={{ border: '1px dashed var(--border-color)', padding: '16px', borderRadius: '8px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <div style={{ fontWeight: 600, fontSize: '14px' }}>Facebook Page Inbox</div>
                  <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>Tự động đồng bộ tin nhắn Messenger của fanpage</div>
                </div>
                <span className="badge pending" style={{ fontSize: '11px' }}>SẮP RA MẮT (PRO)</span>
              </div>
            </div>
          </div>

        </div>

        {/* Panel Phải: Đánh giá chất lượng AI */}
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
              Hệ thống sẽ tự động chạy giả lập **7 kịch bản hội thoại mẫu** chuẩn (Golden Dataset) bao gồm: hỏi giá, hỏi địa chỉ, hỏi giờ làm việc, kích hoạt đặt lịch, và các câu hỏi rủi ro/an toàn y tế (cần handoff gấp) để tính toán điểm số chính xác của AI.
            </p>

            {evalReport ? (
              <div>
                {/* Result Overview Cards */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '12px', marginBottom: '20px' }}>
                  <div style={{ padding: '12px', backgroundColor: '#f8fafc', border: '1px solid var(--border-color)', borderRadius: '8px', textAlign: 'center' }}>
                    <div style={{ fontSize: '10px', uppercase: 'true', color: 'var(--text-muted)', fontWeight: 600 }}>TỔNG SỐ TEST</div>
                    <div style={{ fontSize: '20px', fontWeight: 700, color: 'var(--dark-color)', marginTop: '4px' }}>{evalReport.total_tests}</div>
                  </div>
                  <div style={{ padding: '12px', backgroundColor: '#f8fafc', border: '1px solid var(--border-color)', borderRadius: '8px', textAlign: 'center' }}>
                    <div style={{ fontSize: '10px', uppercase: 'true', color: 'var(--text-muted)', fontWeight: 600 }}>ĐẠT YÊU CẦU</div>
                    <div style={{ fontSize: '20px', fontWeight: 700, color: 'var(--success-color)', marginTop: '4px' }}>{evalReport.passed_tests}</div>
                  </div>
                  <div style={{ padding: '12px', backgroundColor: evalReport.accuracy_rate_percent >= 80 ? '#ecfdf5' : '#fff9e6', border: '1px solid ' + (evalReport.accuracy_rate_percent >= 80 ? 'rgba(16,185,129,0.2)' : 'rgba(245,158,11,0.2)'), borderRadius: '8px', textAlign: 'center' }}>
                    <div style={{ fontSize: '10px', uppercase: 'true', color: evalReport.accuracy_rate_percent >= 80 ? 'var(--success-color)' : 'var(--warning-color)', fontWeight: 600 }}>TỶ LỆ CHÍNH XÁC</div>
                    <div style={{ fontSize: '20px', fontWeight: 700, color: evalReport.accuracy_rate_percent >= 80 ? 'var(--success-color)' : 'var(--warning-color)', marginTop: '4px' }}>
                      {evalReport.accuracy_rate_percent}%
                    </div>
                  </div>
                </div>

                {/* Detail Table */}
                <h4 style={{ fontSize: '13px', fontWeight: 600, color: 'var(--dark-color)', marginBottom: '10px' }}>Kết quả chi tiết kịch bản:</h4>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '350px', overflowY: 'auto' }}>
                  {evalReport.results.map((res) => (
                    <div 
                      key={res.id} 
                      style={{ 
                        border: '1px solid var(--border-color)', 
                        borderRadius: '6px', 
                        padding: '10px 12px', 
                        display: 'flex', 
                        justifyContent: 'space-between', 
                        alignItems: 'center',
                        backgroundColor: res.passed ? '#fcfdfd' : '#fef2f2'
                      }}
                    >
                      <div>
                        <div style={{ fontSize: '13px', fontWeight: 600 }}>Case #{res.id}: {res.description || `Câu hỏi: "${res.query.substring(0, 30)}..."`}</div>
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
              <div style={{ border: '1px dashed var(--border-color)', borderRadius: '8px', padding: '40px', textAlign: 'center', color: 'var(--text-muted)' }}>
                Bấm nút "Chạy Đánh giá AI" ở góc trên bên phải để bắt đầu quá trình kiểm định tự động.
              </div>
            )}
          </div>
        </div>

      </div>
    </div>
  );
}
