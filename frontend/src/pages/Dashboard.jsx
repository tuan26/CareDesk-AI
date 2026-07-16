import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

export default function Dashboard() {
  const [stats, setStats] = useState({
    appointmentsTodayCount: 0,
    conversationsCount: 0,
    pendingAppointmentsCount: 0,
    handoffCount: 0,
  });
  const [todayAppointments, setTodayAppointments] = useState([]);
  const [handoffConversations, setHandoffConversations] = useState([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    const fetchDashboardData = async () => {
      const token = localStorage.getItem('caredesk_token');
      if (!token) {
        navigate('/login');
        return;
      }

      try {
        const headers = { 'Authorization': `Bearer ${token}` };

        // 1. Fetch Appointments
        const apptsRes = await fetch('http://localhost:8000/api/v1/appointments', { headers });
        if (apptsRes.status === 401) throw new Error('Unauthorized');
        const appts = await apptsRes.json();

        // 2. Fetch Conversations
        const convsRes = await fetch('http://localhost:8000/api/v1/chat/conversations', { headers });
        const convs = await convsRes.json();

        // Calculate Stats
        const todayStr = new Date().toISOString().split('T')[0];
        const apptsToday = appts.filter(a => a.start_time.startsWith(todayStr));
        const pendingAppts = appts.filter(a => a.status === 'pending');
        const handoffConvs = convs.filter(c => c.status === 'handoff_requested');

        setStats({
          appointmentsTodayCount: apptsToday.length,
          conversationsCount: convs.length,
          pendingAppointmentsCount: pendingAppts.length,
          handoffCount: handoffConvs.length,
        });

        setTodayAppointments(apptsToday.slice(0, 5));
        setHandoffConversations(handoffConvs);
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

    fetchDashboardData();
  }, [navigate]);

  if (loading) {
    return <div style={{ padding: '24px', textAlign: 'center' }}>Đang tải dữ liệu dashboard...</div>;
  }

  return (
    <div>
      <div className="page-header">
        <div className="page-title">
          <h1>Hệ thống Quản trị Lễ tân ảo</h1>
          <p>Chào mừng trở lại! Dưới đây là số liệu thống kê vận hành hôm nay.</p>
        </div>
      </div>

      {/* Grid Stats */}
      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-info">
            <h3>Lịch hẹn hôm nay</h3>
            <div className="stat-number">{stats.appointmentsTodayCount}</div>
          </div>
          <div className="stat-icon primary">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" width="24" height="24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5" />
            </svg>
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-info">
            <h3>Tổng hội thoại</h3>
            <div className="stat-number">{stats.conversationsCount}</div>
          </div>
          <div className="stat-icon info">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" width="24" height="24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M8.625 12a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H8.25m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H12m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0h-.375M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
            </svg>
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-info">
            <h3>Hẹn chờ xác nhận</h3>
            <div className="stat-number">{stats.pendingAppointmentsCount}</div>
          </div>
          <div className="stat-icon warning">
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" width="24" height="24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
        </div>

        <div className="stat-card" style={stats.handoffCount > 0 ? { border: '1.5px solid var(--danger-color)', backgroundColor: '#fff5f5' } : {}}>
          <div className="stat-info">
            <h3 style={stats.handoffCount > 0 ? { color: 'var(--danger-color)' } : {}}>Handoff Cần hỗ trợ</h3>
            <div className="stat-number" style={stats.handoffCount > 0 ? { color: 'var(--danger-color)' } : {}}>{stats.handoffCount}</div>
          </div>
          <div className="stat-icon" style={stats.handoffCount > 0 ? { backgroundColor: '#fee2e2', color: 'var(--danger-color)' } : { backgroundColor: '#fff7ed', color: '#ea580c' }}>
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" width="24" height="24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
            </svg>
          </div>
        </div>
      </div>

      {/* Main Grid Content */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '24px' }}>
        
        {/* Table Lịch Hẹn Gần Nhất */}
        <div className="card-table-wrapper">
          <div className="card-header">
            <h2>Lịch hẹn hôm nay (5 ca gần nhất)</h2>
            <Link to="/appointments" className="btn btn-secondary btn-sm">Xem tất cả</Link>
          </div>
          {todayAppointments.length === 0 ? (
            <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)' }}>Chưa có lịch hẹn nào được xếp trong ngày hôm nay.</div>
          ) : (
            <table className="custom-table">
              <thead>
                <tr>
                  <th>Khách hàng</th>
                  <th>Dịch vụ</th>
                  <th>Bác sĩ</th>
                  <th>Giờ khám</th>
                  <th>Trạng thái</th>
                </tr>
              </thead>
              <tbody>
                {todayAppointments.map((appt) => (
                  <tr key={appt.id}>
                    <td>
                      <div style={{ fontWeight: 600 }}>{appt.patient?.full_name}</div>
                      <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{appt.patient?.phone}</div>
                    </td>
                    <td>{appt.service?.name}</td>
                    <td>{appt.doctor?.name}</td>
                    <td>{new Date(appt.start_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</td>
                    <td>
                      <span className={`badge ${appt.status}`}>{appt.status}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Handoff Panel */}
        <div className="card-table-wrapper" style={{ height: 'fit-content' }}>
          <div className="card-header" style={{ backgroundColor: '#fffbeb' }}>
            <h2 style={{ color: '#b45309', display: 'flex', alignItems: 'center', gap: '8px' }}>
              ⚠️ Hội thoại khẩn cấp ({stats.handoffCount})
            </h2>
          </div>
          <div style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {handoffConversations.length === 0 ? (
              <div style={{ padding: '16px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '13px' }}>Không có cuộc hội thoại nào cần lễ tân can thiệp.</div>
            ) : (
              handoffConversations.map((conv) => (
                <div 
                  key={conv.id} 
                  style={{
                    border: '1px solid #fde68a',
                    backgroundColor: '#fffdf5',
                    borderRadius: '8px',
                    padding: '12px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '8px'
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontWeight: 600, fontSize: '14px' }}>{conv.patient?.full_name}</span>
                    <span style={{ fontSize: '11px', color: '#b45309', fontWeight: 600, backgroundColor: '#fef3c7', padding: '2px 8px', borderRadius: '4px' }}>
                      CẦN HANDOFF
                    </span>
                  </div>
                  <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>SĐT: {conv.patient?.phone}</div>
                  <Link 
                    to="/inbox" 
                    className="btn btn-primary btn-sm" 
                    style={{ width: '100%', padding: '6px', fontSize: '12px', marginTop: '4px' }}
                  >
                    Tiếp quản ngay
                  </Link>
                </div>
              ))
            )}
          </div>
        </div>

      </div>
    </div>
  );
}
