import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { API_BASE } from '../api';

/** Public chain landing /g/<slug>: lists member clinics, each with its own link. */
export default function ChainPage() {
  const { slug } = useParams();
  const [org, setOrg] = useState(null);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/public/org-by-slug/${slug}`);
        if (!res.ok) { setNotFound(true); return; }
        setOrg(await res.json());
      } catch { setNotFound(true); }
    })();
  }, [slug]);

  if (notFound) return (
    <div style={sx.page}><div style={sx.card}>
      <div style={{ fontSize: 44 }}>🔍</div>
      <h2 style={{ color: '#0f172a' }}>Không tìm thấy chuỗi</h2>
      <p style={{ color: '#64748b' }}>Liên kết <code>/g/{slug}</code> không tồn tại.</p>
    </div></div>
  );
  if (!org) return <div style={sx.page}><div style={sx.card}>Đang tải...</div></div>;

  return (
    <div style={sx.page}>
      <div style={{ width: '100%', maxWidth: 640 }}>
        <h1 style={{ color: '#fff', textAlign: 'center', marginBottom: 4 }}>{org.name}</h1>
        <p style={{ color: 'rgba(255,255,255,.7)', textAlign: 'center', marginBottom: 24, fontSize: 14 }}>
          Chọn cơ sở gần bạn để đặt lịch / trò chuyện với trợ lý ảo
        </p>
        <div style={{ display: 'grid', gap: 12 }}>
          {org.clinics.map(c => (
            <Link key={c.clinic_id} to={`/c/${c.slug}`} style={sx.clinicCard}>
              <div>
                <div style={{ fontWeight: 700, color: '#0f172a', fontSize: 15 }}>{c.name}</div>
                {c.address && <div style={{ color: '#64748b', fontSize: 13 }}>{c.address}</div>}
              </div>
              <span style={sx.cta}>Trò chuyện →</span>
            </Link>
          ))}
          {org.clinics.length === 0 && (
            <div style={sx.card}>Chuỗi này chưa có phòng khám nào đang hoạt động.</div>
          )}
        </div>
        <div style={{ textAlign: 'center', marginTop: 16, fontSize: 11, color: 'rgba(255,255,255,.5)' }}>
          Được vận hành bởi CareDesk AI
        </div>
      </div>
    </div>
  );
}

const sx = {
  page: { minHeight: '100vh', background: 'linear-gradient(135deg,#0f172a,#115e59)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 },
  card: { background: '#fff', borderRadius: 16, padding: 40, maxWidth: 420, textAlign: 'center', boxShadow: '0 10px 30px rgba(0,0,0,.2)' },
  clinicCard: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, background: '#fff', borderRadius: 12, padding: '16px 18px', textDecoration: 'none', boxShadow: '0 4px 20px rgba(0,0,0,.12)' },
  cta: { color: '#0d9488', fontWeight: 600, fontSize: 14, whiteSpace: 'nowrap' },
};
