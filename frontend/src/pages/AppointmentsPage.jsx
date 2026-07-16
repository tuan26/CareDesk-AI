export default function AppointmentsPage() {
  return (
    <div className="page-enter">
      <div className="page-header">
        <h1>Lịch hẹn</h1>
        <p>Quản lý lịch hẹn khám bệnh</p>
      </div>
      <div className="card">
        <div className="empty-state">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="4" width="18" height="18" rx="2" />
            <line x1="16" y1="2" x2="16" y2="6" />
            <line x1="8" y1="2" x2="8" y2="6" />
            <line x1="3" y1="10" x2="21" y2="10" />
          </svg>
          <h3>Chưa có dữ liệu</h3>
          <p>Trang quản lý lịch hẹn đang được phát triển.</p>
        </div>
      </div>
    </div>
  )
}
