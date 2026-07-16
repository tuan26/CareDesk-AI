export default function DoctorsPage() {
  return (
    <div className="page-enter">
      <div className="page-header">
        <h1>Bác sĩ</h1>
        <p>Quản lý danh sách bác sĩ và nhân viên y tế</p>
      </div>
      <div className="card">
        <div className="empty-state">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M16 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
            <circle cx="10" cy="7" r="4" />
            <line x1="18" y1="8" x2="18" y2="14" />
            <line x1="15" y1="11" x2="21" y2="11" />
          </svg>
          <h3>Chưa có dữ liệu</h3>
          <p>Trang quản lý bác sĩ đang được phát triển.</p>
        </div>
      </div>
    </div>
  )
}
