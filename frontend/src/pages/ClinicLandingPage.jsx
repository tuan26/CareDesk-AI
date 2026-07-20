import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { API_BASE } from '../api';

/** Public clinic page /org/<orgSlug>/clinics/<clinicSlug>: branding + CTA into the chat. */
export default function ClinicLandingPage() {
  const { orgSlug, clinicSlug } = useParams();
  const [clinic, setClinic] = useState(null);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/public/org/${orgSlug}/clinics/${clinicSlug}`);
        if (!res.ok) { setNotFound(true); return; }
        setClinic(await res.json());
      } catch { setNotFound(true); }
    })();
  }, [orgSlug, clinicSlug]);

  if (notFound) return (
    <div style={sx.page}><div style={sx.card}>
      <div style={{ fontSize: 44 }}>🔍</div>
      <h2 style={{ color: '#0f172a' }}>Không tìm thấy phòng khám</h2>
      <p style={{ color: '#64748b' }}>Phòng khám không thuộc chuỗi này hoặc liên kết đã thay đổi.</p>
    </div></div>
  );
  if (!clinic) return <div style={sx.page}><div style={sx.card}>Đang tải...</div></div>;

  return (
    <div style={sx.page}>
      <div style={sx.card}>
        {clinic.logo_url
          ? <img src={clinic.logo_url} alt="" style={sx.logo} />
          : <div style={{ ...sx.logo, ...sx.logoFallback }}>{clinic.name.slice(0, 1)}</div>}
        <h1 style={{ color: '#0f172a', fontSize: 22, margin: '14px 0 6px' }}>{clinic.name}</h1>
        {clinic.address && <p style={{ color: '#64748b', fontSize: 14, margin: 0 }}>📍 {clinic.address}</p>}
        {clinic.phone && <p style={{ color: '#64748b', fontSize: 14, margin: '4px 0 0' }}>☎ {clinic.phone}</p>}
        {!clinic.is_active && (
          <p style={{ color: '#dc2626', fontSize: 13, marginTop: 12 }}>Phòng khám đang tạm ngưng nhận tư vấn tự động.</p>
        )}
        <Link to={`/book/${orgSlug}/${clinicSlug}/chat`} style={sx.btn}>
          💬 Trò chuyện với trợ lý ảo
        </Link>
        <Link to={`/book/${orgSlug}`} style={sx.back}>← Xem các cơ sở khác trong chuỗi</Link>
      </div>
    </div>
  );
}

const sx = {
  page: { minHeight: '100vh', background: 'linear-gradient(135deg,#0f172a,#115e59)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 },
  card: { background: '#fff', borderRadius: 18, padding: '36px 32px', maxWidth: 440, width: '100%', textAlign: 'center', boxShadow: '0 12px 40px rgba(0,0,0,.25)' },
  logo: { width: 72, height: 72, borderRadius: 16, objectFit: 'cover', margin: '0 auto' },
  logoFallback: { background: '#0d9488', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700, fontSize: 32 },
  btn: { display: 'block', marginTop: 22, padding: 14, fontSize: 15, fontWeight: 600, color: '#fff', background: 'linear-gradient(135deg,#14b8a6,#0f766e)', borderRadius: 10, textDecoration: 'none' },
  back: { display: 'inline-block', marginTop: 14, fontSize: 13, color: '#64748b', textDecoration: 'none' },
};
