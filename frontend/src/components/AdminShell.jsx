import { useNavigate } from 'react-router-dom';

/**
 * Standalone chrome for platform / chain admin consoles.
 * These roles have no clinic data, so they do NOT use the clinic sidebar Layout.
 */
export default function AdminShell({ user, badge, title, subtitle, children }) {
  const navigate = useNavigate();
  const logout = () => {
    localStorage.removeItem('caredesk_token');
    navigate('/login');
  };
  const initials = (user?.full_name || 'US').split(' ').map(n => n[0]).join('').toUpperCase().slice(0, 2);

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg-main)' }}>
      <header style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '14px 28px', background: 'var(--dark-color)', color: 'white',
        position: 'sticky', top: 0, zIndex: 10, boxShadow: 'var(--shadow-md)'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{
            width: 34, height: 34, borderRadius: 8, background: 'var(--primary-color)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700, fontSize: 13
          }}>CD</div>
          <div>
            <div style={{ fontWeight: 700, fontSize: 15 }}>CareDesk AI</div>
            <div style={{ fontSize: 11, color: '#94a3b8' }}>{badge}</div>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: 13, fontWeight: 600 }}>{user?.full_name}</div>
            <div style={{ fontSize: 11, color: '#94a3b8' }}>{(user?.role || '').toUpperCase()}</div>
          </div>
          <div style={{
            width: 34, height: 34, borderRadius: '50%', background: 'var(--primary-color)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700, fontSize: 12
          }}>{initials}</div>
          <button className="btn btn-sm" style={{
            background: 'transparent', color: '#cbd5e1', border: '1px solid rgba(255,255,255,0.25)'
          }} onClick={logout}>Đăng xuất</button>
        </div>
      </header>

      <div style={{ maxWidth: 1180, margin: '0 auto', padding: '28px' }}>
        <div className="page-header">
          <div className="page-title">
            <h1>{title}</h1>
            {subtitle && <p>{subtitle}</p>}
          </div>
        </div>
        {children}
      </div>
    </div>
  );
}
