import { useEffect, useState } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { API_BASE } from '../api';
import { useI18n } from '../i18n';


export default function Layout() {
  const [user, setUser] = useState(null);
  const [actingClinic, setActingClinic] = useState(null);
  const navigate = useNavigate();
  const { locale, setLocale, t } = useI18n();


  useEffect(() => {
    const fetchUser = async () => {
      const token = localStorage.getItem('caredesk_token');
      if (!token) {
        navigate('/login');
        return;
      }

      try {
        const response = await fetch(`${API_BASE}/auth/me`, {
          headers: {
            'Authorization': `Bearer ${token}`,
          },
        });
        if (!response.ok) {
          throw new Error('Unauthorized');
        }
        const data = await response.json();
        // A chain owner "managing" a clinic carries a scoped token + this marker.
        const acting = JSON.parse(localStorage.getItem('caredesk_active_clinic') || 'null');
        // Platform admins / chain owners (when NOT inside a clinic) go to their console.
        if (data.is_platform_admin && !acting) { navigate('/platform'); return; }
        if (data.organization_id && !acting) { navigate('/org'); return; }
        setUser(data);
        setActingClinic(acting);
      } catch (err) {
        localStorage.removeItem('caredesk_token');
        navigate('/login');
      }
    };

    fetchUser();
  }, [navigate]);

  const handleLogout = () => {
    localStorage.removeItem('caredesk_token');
    localStorage.removeItem('caredesk_org_token');
    localStorage.removeItem('caredesk_active_clinic');
    navigate('/login');
  };

  // Return a chain owner from a clinic back to their chain console.
  const backToChain = () => {
    const base = localStorage.getItem('caredesk_org_token');
    if (base) localStorage.setItem('caredesk_token', base);
    localStorage.removeItem('caredesk_org_token');
    const orgSlug = actingClinic?.orgSlug;
    localStorage.removeItem('caredesk_active_clinic');
    navigate(orgSlug ? `/org/${orgSlug}` : '/org');
  };

  if (!user) {
    return <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>Đang tải...</div>;
  }

  const getInitials = (name) => {
    return name ? name.split(' ').map(n => n[0]).join('').toUpperCase().substring(0, 2) : 'US';
  };

  // Menu theo hành trình khách hàng (triết lý Revenue Engine)
    const MENU_SECTIONS = [
    { label: t('attract'), items: [
      { to: '/', icon: '📊', text: t('dashboard'), end: true },
      { to: '/inbox', icon: '💬', text: t('inbox') },
      { to: '/booking-requests', icon: '📨', text: t('bookings') },
      { to: '/appointments', icon: '📅', text: t('appointments') },
    ] },
    { label: t('retain'), items: [
      { to: '/patients', icon: '👥', text: t('patients') }, { to: '/packages', icon: '🎁', text: t('packages') }, { to: '/automation', icon: '⚡', text: t('automation') },
    ] },
    { label: t('analytics'), items: [{ to: '/reports', icon: '📈', text: t('reports') }] },
    { label: t('system'), items: [
      { to: '/onboarding', icon: '🚀', text: 'Thiết lập' },
      { to: '/clinic', icon: '🏥', text: t('clinic') }, { to: '/services', icon: '🧴', text: t('services') }, { to: '/doctors', icon: '🩺', text: t('doctors') }, { to: '/settings', icon: '⚙️', text: t('settings') },
    ] },
  ];


  return (
    <div className="app-container">
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="sidebar-logo">
          <div className="logo-symbol">CD</div>
          CareDesk AI
        </div>
        <div style={{ flex: 1, overflowY: 'auto' }}>
          {MENU_SECTIONS.map((section) => (
            <div key={section.label} style={{ marginBottom: '14px' }}>
              <div style={{ fontSize: '10px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.8px', color: '#64748b', padding: '0 16px', marginBottom: '6px' }}>
                {section.label}
              </div>
              <ul className="sidebar-menu" style={{ flex: 'none', gap: '2px' }}>
                {section.items.map((item) => (
                  <li className="sidebar-item" key={item.to}>
                    <NavLink to={item.to} end={item.end}>
                      <span style={{ fontSize: '15px', width: '20px', textAlign: 'center' }}>{item.icon}</span>
                      {item.text}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
                <div style={{ marginTop: 'auto', borderTop: '1px solid rgba(255,255,255,0.1)', paddingTop: '16px' }}>
          <select aria-label="Language" value={locale} onChange={(e) => setLocale(e.target.value)} style={{ width: '100%', marginBottom: 8, padding: '7px', borderRadius: 5 }}>
            <option value="vi">Tiếng Việt</option><option value="en">English</option><option value="ja">日本語</option>
          </select>
          <button 
 
            className="btn btn-secondary" 
            style={{ width: '100%', background: 'transparent', color: '#94a3b8', border: '1px solid rgba(255,255,255,0.2)', fontSize: '13px' }}
            onClick={handleLogout}
          >
                        {t('logout')}

          </button>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="main-content">
        <header className="header-bar">
          <div className="user-profile">
            <div className="user-avatar">{getInitials(user.full_name)}</div>
            <div style={{ textAlign: 'left' }}>
              <div className="user-name">{user.full_name}</div>
              <div className="user-role">{user.role.toUpperCase()}</div>
            </div>
          </div>
        </header>

        {actingClinic && (
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12,
            padding: '8px 24px', background: '#0f766e', color: '#fff', fontSize: 13
          }}>
            <span>🔗 Bạn đang quản lý <b>{actingClinic.name}</b> (thuộc chuỗi của bạn).</span>
            <button className="btn btn-sm" style={{ background: 'rgba(255,255,255,0.15)', color: '#fff', border: '1px solid rgba(255,255,255,0.35)' }}
              onClick={backToChain}>← Về Console chuỗi</button>
          </div>
        )}

        <section className="page-body">
          <Outlet />
        </section>
      </main>
    </div>
  );
}
