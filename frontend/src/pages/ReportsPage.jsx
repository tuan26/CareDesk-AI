import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { API_BASE, getAuthHeaders } from '../api';

const STATUS_LABELS = {
  pending: 'Chờ xác nhận', confirmed: 'Đã xác nhận', completed: 'Hoàn thành',
  cancelled: 'Đã hủy', no_show: 'Vắng mặt'
};

const fmtMoney = (v) => new Intl.NumberFormat('vi-VN').format(v || 0) + 'đ';

function BarChart({ data, valueKey, labelKey, formatValue }) {
  const max = Math.max(...data.map(d => d[valueKey]), 1);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
      {data.map((d, i) => (
        <div key={i}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', marginBottom: '3px' }}>
            <span style={{ fontWeight: 600, color: 'var(--dark-color)' }}>{d[labelKey]}</span>
            <span style={{ color: 'var(--text-muted)' }}>{formatValue ? formatValue(d[valueKey]) : d[valueKey]}</span>
          </div>
          <div style={{ background: '#f1f5f9', borderRadius: '4px', height: '8px', overflow: 'hidden' }}>
            <div style={{ width: `${(d[valueKey] / max) * 100}%`, height: '100%', background: 'var(--primary-color)', borderRadius: '4px' }} />
          </div>
        </div>
      ))}
      {data.length === 0 && <div style={{ fontSize: '13px', color: 'var(--text-muted)' }}>Chưa có dữ liệu trong khoảng thời gian này.</div>}
    </div>
  );
}

export default function ReportsPage() {
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const today = new Date().toISOString().split('T')[0];
  const monthAgo = new Date(Date.now() - 29 * 86400000).toISOString().split('T')[0];
  const [startDate, setStartDate] = useState(monthAgo);
  const [endDate, setEndDate] = useState(today);
  const navigate = useNavigate();

  const fetchReport = async () => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({ start_date: startDate, end_date: endDate });
      const res = await fetch(`${API_BASE}/reports/summary?${params}`, { headers: getAuthHeaders() });
      if (res.status === 401) {
        localStorage.removeItem('caredesk_token');
        navigate('/login');
        return;
      }
      if (res.status === 403) {
        setError('Chỉ chủ phòng khám mới xem được báo cáo.');
        return;
      }
      setReport(await res.json());
    } catch (err) {
      console.error(err);
      setError('Không thể tải báo cáo.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchReport();
  }, [startDate, endDate]);

  if (loading && !report) return <div style={{ padding: '24px', textAlign: 'center' }}>Đang tải báo cáo...</div>;

  return (
    <div>
      <div className="page-header">
        <div className="page-title">
          <h1>Báo cáo vận hành</h1>
          <p>Doanh thu, tỷ lệ chuyển đổi từ hội thoại AI và hiệu suất chống no-show.</p>
        </div>
        <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
          <input className="form-control" type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} style={{ width: 'auto' }} />
          <span style={{ color: 'var(--text-muted)' }}>→</span>
          <input className="form-control" type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} style={{ width: 'auto' }} />
        </div>
      </div>

      {error ? (
        <div className="card-table-wrapper" style={{ padding: '32px', textAlign: 'center', color: 'var(--danger-color)' }}>{error}</div>
      ) : report && (
        <>
          {/* Revenue Engine hero */}
          <div className="stats-grid">
            <div className="stat-card" style={{ borderTop: '3px solid var(--primary-color)' }}>
              <div className="stat-info">
                <h3>💰 Doanh thu AI tạo ra</h3>
                <div className="stat-number" style={{ fontSize: '22px', color: 'var(--primary-color)' }}>{fmtMoney(report.totals.ai_revenue)}</div>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
                  Tổng sổ doanh thu: {fmtMoney(report.totals.ledger_revenue)}
                </div>
              </div>
            </div>
            <div className="stat-card" style={{ borderTop: '3px solid #10b981' }}>
              <div className="stat-info">
                <h3>ROI trên phí CareDesk</h3>
                <div className="stat-number" style={{ fontSize: '22px', color: '#10b981' }}>
                  {report.totals.roi != null ? `${report.totals.roi}x` : '—'}
                </div>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
                  {report.totals.monthly_fee > 0 ? `Phí gói: ${fmtMoney(report.totals.monthly_fee)}/tháng` : 'Chưa cấu hình phí gói'}
                </div>
              </div>
            </div>
            <div className="stat-card" style={{ borderTop: '3px solid #3b82f6' }}>
              <div className="stat-info">
                <h3>Khách quay lại (2+ lần)</h3>
                <div className="stat-number" style={{ fontSize: '22px' }}>{report.totals.returning_patients}</div>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
                  Automation giữ chân đang hoạt động
                </div>
              </div>
            </div>
            <div className="stat-card" style={{ borderTop: '3px solid #f59e0b' }}>
              <div className="stat-info">
                <h3>Gói liệu trình</h3>
                <div className="stat-number" style={{ fontSize: '22px' }}>{report.totals.active_packages}</div>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
                  Giá trị buổi chưa dùng: {fmtMoney(report.totals.unused_package_value)}
                </div>
              </div>
            </div>
          </div>

          {/* Stat cards */}
          <div className="stats-grid">
            <div className="stat-card">
              <div className="stat-info">
                <h3>Doanh thu dự kiến</h3>
                <div className="stat-number" style={{ fontSize: '22px' }}>{fmtMoney(report.totals.expected_revenue)}</div>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
                  Thực thu (hoàn thành): {fmtMoney(report.totals.actual_revenue)}
                </div>
              </div>
              <div className="stat-icon success">💰</div>
            </div>
            <div className="stat-card">
              <div className="stat-info">
                <h3>Lịch hẹn / Hội thoại</h3>
                <div className="stat-number">{report.totals.appointments} / {report.totals.conversations}</div>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
                  Tỷ lệ chuyển đổi: <b>{report.conversion_rate_percent}%</b>
                </div>
              </div>
              <div className="stat-icon primary">📈</div>
            </div>
            <div className="stat-card">
              <div className="stat-info">
                <h3>Tỷ lệ No-show</h3>
                <div className="stat-number" style={{ color: report.no_show_rate_percent > 20 ? 'var(--danger-color)' : 'var(--success-color)' }}>
                  {report.no_show_rate_percent}%
                </div>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
                  Trên số ca đã kết thúc (hoàn thành + vắng)
                </div>
              </div>
              <div className="stat-icon warning">🚫</div>
            </div>
            <div className="stat-card">
              <div className="stat-info">
                <h3>AI tự chốt lịch</h3>
                <div className="stat-number">{report.totals.ai_booked_appointments}</div>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
                  Handoff cần người thật: <b>{report.handoff_rate_percent}%</b>
                </div>
              </div>
              <div className="stat-icon info">🤖</div>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
            <div className="card-table-wrapper">
              <div className="card-header"><h2>Doanh thu theo nguồn (attribution)</h2></div>
              <div style={{ padding: '20px 24px' }}>
                <BarChart
                  data={Object.entries(report.revenue_by_source || {}).map(([k, v]) => ({
                    label: { ai_chat: '🤖 AI chốt trong chat', ai_followup: '🤖 AI follow-up', staff: 'Lễ tân', package: '🎁 Bán gói', campaign: 'Chiến dịch', referral: 'Giới thiệu' }[k] || k,
                    value: v
                  }))}
                  valueKey="value" labelKey="label" formatValue={fmtMoney}
                />
              </div>
            </div>

            <div className="card-table-wrapper">
              <div className="card-header"><h2>Doanh thu theo dịch vụ</h2></div>
              <div style={{ padding: '20px 24px' }}>
                <BarChart data={report.revenue_by_service} valueKey="revenue" labelKey="name" formatValue={fmtMoney} />
              </div>
            </div>

            <div className="card-table-wrapper">
              <div className="card-header"><h2>Doanh thu theo bác sĩ</h2></div>
              <div style={{ padding: '20px 24px' }}>
                <BarChart data={report.revenue_by_doctor} valueKey="revenue" labelKey="name" formatValue={fmtMoney} />
              </div>
            </div>

            <div className="card-table-wrapper">
              <div className="card-header"><h2>Trạng thái lịch hẹn</h2></div>
              <div style={{ padding: '20px 24px' }}>
                <BarChart
                  data={Object.entries(report.status_counts).map(([k, v]) => ({ label: STATUS_LABELS[k] || k, count: v }))}
                  valueKey="count" labelKey="label"
                />
              </div>
            </div>

            <div className="card-table-wrapper">
              <div className="card-header"><h2>Khung giờ cao điểm</h2></div>
              <div style={{ padding: '20px 24px' }}>
                <div style={{ display: 'flex', alignItems: 'flex-end', gap: '4px', height: '140px' }}>
                  {report.peak_hours.map((p) => {
                    const max = Math.max(...report.peak_hours.map(x => x.count), 1);
                    return (
                      <div key={p.hour} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '4px', height: '100%', justifyContent: 'flex-end' }}>
                        <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{p.count > 0 ? p.count : ''}</span>
                        <div style={{
                          width: '100%',
                          height: `${Math.max((p.count / max) * 100, 2)}%`,
                          background: p.count > 0 ? 'var(--primary-color)' : '#e2e8f0',
                          borderRadius: '3px 3px 0 0'
                        }} />
                        <span style={{ fontSize: '9px', color: 'var(--text-muted)' }}>{p.hour}h</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
