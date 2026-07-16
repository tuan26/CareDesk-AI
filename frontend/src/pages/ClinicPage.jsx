export default function ClinicPage() {
  return (
    <div className="page-enter">
      <div className="page-header">
        <h1>Phòng khám</h1>
        <p>Quản lý thông tin phòng khám</p>
      </div>
      <div className="card">
        <div className="empty-state">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 21h18" /><path d="M5 21V7l7-4 7 4v14" /><path d="M9 21v-6h6v6" />
          </svg>
          <h3>Chưa có dữ liệu</h3>
          <p>Trang quản lý phòng khám đang được phát triển.</p>
        </div>
      </div>
    </div>
  )
}
