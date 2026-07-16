export default function ServicesPage() {
  return (
    <div className="page-enter">
      <div className="page-header">
        <h1>Dịch vụ</h1>
        <p>Quản lý danh sách dịch vụ khám chữa bệnh</p>
      </div>
      <div className="card">
        <div className="empty-state">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2" />
            <rect x="9" y="3" width="6" height="4" rx="1" />
          </svg>
          <h3>Chưa có dữ liệu</h3>
          <p>Trang quản lý dịch vụ đang được phát triển.</p>
        </div>
      </div>
    </div>
  )
}
