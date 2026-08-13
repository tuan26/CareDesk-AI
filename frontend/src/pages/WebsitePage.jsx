import { useEffect, useState } from 'react';
import { API_BASE, getAuthHeaders } from '../api';

/**
 * What the public site says, and what it is allowed to show.
 *
 * Three tabs, in the order they matter. Copy is the least important — it ships
 * with sensible Vietnamese defaults, so the page already reads well before
 * anyone touches it. The other two are where the value is: before/after photos
 * and written reviews are the two things that actually convert an aesthetics
 * visitor, and both already accumulate from ordinary operations. The clinic
 * chooses; it does not have to produce.
 *
 * Publishing a patient's photo or words is deliberately a two-step act. Consent
 * is recorded separately from publication so "did she agree?" and "did we
 * choose to show it?" stay different questions with different answers.
 */

const TABS = [
  { id: 'content', label: 'Nội dung trang' },
  { id: 'photos', label: 'Ảnh trước / sau' },
  { id: 'reviews', label: 'Đánh giá' },
];

export default function WebsitePage() {
  const [tab, setTab] = useState('content');
  const [user, setUser] = useState(null);

  useEffect(() => {
    fetch(`${API_BASE}/auth/me`, { headers: getAuthHeaders() })
      .then((r) => (r.ok ? r.json() : null))
      .then(setUser)
      .catch(() => {});
  }, []);

  const isOwner = user?.role === 'owner';

  return (
    <div>
      <div className="page-header">
        <div className="page-title">
          <h1>Website phòng khám</h1>
          <p>Nội dung hiển thị trên trang công khai — nơi khách nhìn thấy trước khi đặt lịch.</p>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 4, borderBottom: '1px solid var(--border-color)', marginBottom: 20 }}>
        {TABS.map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)}
            style={{
              padding: '10px 18px', border: 'none', background: 'none', cursor: 'pointer',
              fontSize: 14, fontWeight: tab === t.id ? 700 : 500,
              color: tab === t.id ? 'var(--primary-color)' : 'var(--text-muted)',
              borderBottom: tab === t.id ? '2px solid var(--primary-color)' : '2px solid transparent',
            }}>
            {t.label}
          </button>
        ))}
      </div>

      {!isOwner && (
        <div style={{ background: '#fef3c7', border: '1px solid #fde68a', padding: '10px 14px', borderRadius: 8, marginBottom: 16, fontSize: 13.5, color: '#92400e' }}>
          Chỉ chủ phòng khám mới sửa được nội dung website. Bạn đang ở chế độ xem.
        </div>
      )}

      {tab === 'content' && <ContentTab canEdit={isOwner} />}
      {tab === 'photos' && <PhotosTab canEdit={isOwner} />}
      {tab === 'reviews' && <ReviewsTab canEdit={isOwner} />}
    </div>
  );
}

/* ---------------------------------------------------------------- copy ---- */

function ContentTab({ canEdit }) {
  const [schema, setSchema] = useState([]);
  const [values, setValues] = useState({});
  const [dirty, setDirty] = useState({});
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState('');

  useEffect(() => {
    fetch(`${API_BASE}/content/site`, { headers: getAuthHeaders() })
      .then((r) => r.json())
      .then((d) => { setSchema(d.schema || []); setValues(d.values || {}); })
      .catch(() => setMsg('Không tải được nội dung.'));
  }, []);

  const set = (key, value) => {
    setValues({ ...values, [key]: value });
    setDirty({ ...dirty, [key]: true });
  };

  const save = async () => {
    setSaving(true);
    setMsg('');
    const payload = {};
    for (const key of Object.keys(dirty)) payload[key] = values[key];
    const res = await fetch(`${API_BASE}/content/site`, {
      method: 'PUT', headers: getAuthHeaders(), body: JSON.stringify({ values: payload }),
    });
    setSaving(false);
    if (!res.ok) { setMsg('Không lưu được.'); return; }
    setValues((await res.json()).values);
    setDirty({});
    setMsg('Đã lưu. Trang công khai cập nhật sau tối đa 5 phút (bộ nhớ đệm).');
  };

  const changed = Object.keys(dirty).length;

  return (
    <div className="card-table-wrapper" style={{ padding: 24 }}>
      {schema.map((f) => (
        <div key={f.key} style={{ marginBottom: 22, maxWidth: 720 }}>
          <label style={{ fontWeight: 600, fontSize: 14, display: 'block', marginBottom: 4 }}>
            {f.label}
          </label>
          {f.hint && (
            <div style={{ fontSize: 12.5, color: 'var(--text-muted)', marginBottom: 6 }}>{f.hint}</div>
          )}

          {f.kind === 'textarea' && (
            <textarea className="form-control" rows="2" disabled={!canEdit}
              value={values[f.key] || ''} onChange={(e) => set(f.key, e.target.value)} />
          )}
          {f.kind === 'text' && (
            <input className="form-control" disabled={!canEdit}
              value={values[f.key] || ''} onChange={(e) => set(f.key, e.target.value)} />
          )}
          {f.kind === 'stats' && (
            <StatsEditor canEdit={canEdit} value={values[f.key] || []}
              onChange={(v) => set(f.key, v)} />
          )}
          {f.kind === 'list' && (
            <ListEditor canEdit={canEdit} value={values[f.key] || []}
              onChange={(v) => set(f.key, v)} />
          )}
        </div>
      ))}

      {canEdit && (
        <div style={{ position: 'sticky', bottom: 0, background: '#fff', paddingTop: 12, borderTop: '1px solid var(--border-color)', display: 'flex', gap: 12, alignItems: 'center' }}>
          <button className="btn btn-primary" onClick={save} disabled={saving || !changed}>
            {saving ? 'Đang lưu…' : changed ? `Lưu ${changed} thay đổi` : 'Chưa có thay đổi'}
          </button>
          {msg && <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>{msg}</span>}
        </div>
      )}
    </div>
  );
}

function StatsEditor({ value, onChange, canEdit }) {
  const rows = value.length ? value : [{ value: '', label: '' }];
  const update = (i, field, v) => {
    const next = rows.map((r, idx) => (idx === i ? { ...r, [field]: v } : r));
    onChange(next);
  };
  return (
    <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
      {rows.map((r, i) => (
        <div key={i} style={{ display: 'flex', gap: 6 }}>
          <input className="form-control" style={{ width: 110 }} placeholder="10+"
            disabled={!canEdit} value={r.value || ''}
            onChange={(e) => update(i, 'value', e.target.value)} />
          <input className="form-control" style={{ width: 190 }} placeholder="năm kinh nghiệm"
            disabled={!canEdit} value={r.label || ''}
            onChange={(e) => update(i, 'label', e.target.value)} />
        </div>
      ))}
    </div>
  );
}

function ListEditor({ value, onChange, canEdit }) {
  const rows = value.length ? value : [{ title: '', body: '' }];
  const update = (i, field, v) =>
    onChange(rows.map((r, idx) => (idx === i ? { ...r, [field]: v } : r)));
  return (
    <div>
      {rows.map((r, i) => (
        <div key={i} style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
          <input className="form-control" style={{ maxWidth: 220 }} placeholder="Tiêu đề bước"
            disabled={!canEdit} value={r.title || ''}
            onChange={(e) => update(i, 'title', e.target.value)} />
          <input className="form-control" placeholder="Mô tả"
            disabled={!canEdit} value={r.body || ''}
            onChange={(e) => update(i, 'body', e.target.value)} />
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------- photos ---- */

function PhotosTab({ canEdit }) {
  const [photos, setPhotos] = useState([]);
  const [msg, setMsg] = useState('');
  const [loading, setLoading] = useState(true);

  const load = () =>
    fetch(`${API_BASE}/content/photos`, { headers: getAuthHeaders() })
      .then((r) => r.json())
      .then((d) => setPhotos(Array.isArray(d) ? d : []))
      .finally(() => setLoading(false));

  useEffect(() => { load(); }, []);

  const setConsent = async (photo, given) => {
    if (given && !window.confirm(
      'Xác nhận khách hàng ĐÃ ĐỒNG Ý cho phòng khám dùng ảnh này công khai?\n\n' +
      'Đây là ảnh bệnh nhân. Chỉ tích khi bạn thực sự đã hỏi và được đồng ý.')) return;
    const res = await fetch(`${API_BASE}/content/photos/${photo.id}/consent`, {
      method: 'PUT', headers: getAuthHeaders(),
      body: JSON.stringify({ consent_given: given, note: null }),
    });
    if (!res.ok) { setMsg('Không cập nhật được.'); return; }
    setMsg(given ? 'Đã ghi nhận đồng ý.' : 'Đã thu hồi đồng ý và gỡ ảnh khỏi trang công khai.');
    load();
  };

  const setPublished = async (photo, published) => {
    const res = await fetch(`${API_BASE}/content/photos/${photo.id}/publish`, {
      method: 'PUT', headers: getAuthHeaders(),
      body: JSON.stringify({ is_published: published }),
    });
    if (!res.ok) {
      setMsg((await res.json()).detail || 'Không đăng được.');
      return;
    }
    setMsg('');
    load();
  };

  if (loading) return <div style={{ padding: 24 }}>Đang tải…</div>;

  return (
    <div>
      <div style={{ background: '#f0fdfa', border: '1px solid #99f6e4', padding: '12px 16px', borderRadius: 8, marginBottom: 16, fontSize: 13.5 }}>
        Ảnh trước/sau là thứ thuyết phục nhất trên trang web thẩm mỹ. Nhưng đây là
        <b> ảnh bệnh nhân</b> — chỉ đăng khi đã hỏi và được khách đồng ý. Thu hồi
        đồng ý sẽ gỡ ảnh khỏi trang ngay lập tức.
      </div>
      {msg && <div style={{ marginBottom: 12, fontSize: 13.5, color: 'var(--text-muted)' }}>{msg}</div>}

      {photos.length === 0 ? (
        <div className="card-table-wrapper" style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>
          Chưa có ảnh nào. Ảnh được chụp trong lúc ghi hồ sơ ở màn hình Hàng đợi khám.
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(230px,1fr))', gap: 16 }}>
          {photos.map((p) => (
            <div key={p.id} className="card-table-wrapper" style={{ padding: 12 }}>
              <AuthImage url={p.url} />
              <div style={{ fontSize: 12, color: 'var(--text-muted)', margin: '8px 0 4px' }}>
                {p.kind === 'before' ? 'Trước' : 'Sau'}
                {p.service_name && ` · ${p.service_name}`}
              </div>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>{p.patient_name || '—'}</div>

              <label style={{ display: 'flex', gap: 7, alignItems: 'flex-start', fontSize: 12.5, marginBottom: 6 }}>
                <input type="checkbox" checked={p.has_consent} disabled={!canEdit}
                  onChange={(e) => setConsent(p, e.target.checked)} style={{ marginTop: 2 }} />
                <span>Khách đồng ý cho đăng</span>
              </label>
              <label style={{ display: 'flex', gap: 7, alignItems: 'flex-start', fontSize: 12.5,
                              opacity: p.has_consent ? 1 : 0.45 }}>
                <input type="checkbox" checked={p.is_published}
                  disabled={!canEdit || !p.has_consent}
                  onChange={(e) => setPublished(p, e.target.checked)} style={{ marginTop: 2 }} />
                <span>Hiển thị trên website</span>
              </label>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Patient photos are served from an authenticated endpoint, so a plain <img src>
 * would 401 — the browser sends no Authorization header. Fetch as a blob instead.
 */
function AuthImage({ url }) {
  const [src, setSrc] = useState(null);
  useEffect(() => {
    let objectUrl;
    const token = localStorage.getItem('caredesk_token');
    const full = url.startsWith('http') ? url : API_BASE.replace(/\/api\/v1$/, '') + url;
    fetch(full, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => (r.ok ? r.blob() : null))
      .then((b) => { if (b) { objectUrl = URL.createObjectURL(b); setSrc(objectUrl); } })
      .catch(() => {});
    return () => objectUrl && URL.revokeObjectURL(objectUrl);
  }, [url]);

  return (
    <div style={{ aspectRatio: '1', background: '#f1f5f9', borderRadius: 6, overflow: 'hidden' }}>
      {src && <img src={src} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />}
    </div>
  );
}

/* ------------------------------------------------------------ reviews ---- */

function ReviewsTab({ canEdit }) {
  const [reviews, setReviews] = useState([]);
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState('');

  const load = () =>
    fetch(`${API_BASE}/content/reviews`, { headers: getAuthHeaders() })
      .then((r) => r.json())
      .then((d) => setReviews(Array.isArray(d) ? d : []))
      .finally(() => setLoading(false));

  useEffect(() => { load(); }, []);

  const publish = async (r, published, publicName) => {
    const res = await fetch(`${API_BASE}/content/reviews/${r.id}/publish`, {
      method: 'PUT', headers: getAuthHeaders(),
      body: JSON.stringify({ is_published: published, public_name: publicName }),
    });
    if (!res.ok) { setMsg((await res.json()).detail || 'Không cập nhật được.'); return; }
    setMsg('');
    load();
  };

  if (loading) return <div style={{ padding: 24 }}>Đang tải…</div>;

  return (
    <div>
      <div style={{ background: '#f0fdfa', border: '1px solid #99f6e4', padding: '12px 16px', borderRadius: 8, marginBottom: 16, fontSize: 13.5 }}>
        Đánh giá do hệ thống tự hỏi khách sau mỗi buổi khám. Chọn những đánh giá
        bạn muốn hiển thị, và <b>đặt tên rút gọn</b> (vd. “Chị Ngọc A.”) — đừng
        dùng tên đầy đủ của khách trên trang công khai.
      </div>
      {msg && <div style={{ marginBottom: 12, fontSize: 13.5, color: '#b91c1c' }}>{msg}</div>}

      {reviews.length === 0 ? (
        <div className="card-table-wrapper" style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>
          Chưa có đánh giá nào. Hệ thống sẽ tự hỏi khách 2 giờ sau buổi khám.
        </div>
      ) : (
        <div className="card-table-wrapper">
          <table className="data-table">
            <thead>
              <tr><th>Điểm</th><th>Nội dung</th><th>Khách</th><th>Tên hiển thị</th><th>Website</th></tr>
            </thead>
            <tbody>
              {reviews.map((r) => (
                <ReviewRow key={r.id} r={r} canEdit={canEdit} onPublish={publish} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function ReviewRow({ r, canEdit, onPublish }) {
  const [name, setName] = useState(r.public_name || '');

  return (
    <tr>
      <td style={{ color: '#B99A5B', whiteSpace: 'nowrap' }}>{'★'.repeat(r.rating || 0)}</td>
      <td style={{ maxWidth: 380, fontSize: 13.5 }}>{r.feedback || <span style={{ color: 'var(--text-muted)' }}>(chỉ chấm điểm, không có nội dung)</span>}</td>
      <td style={{ fontSize: 13 }}>{r.patient_name || '—'}</td>
      <td>
        <input className="form-control" style={{ width: 150, fontSize: 13 }}
          placeholder="Chị Ngọc A." value={name} disabled={!canEdit || !r.feedback}
          onChange={(e) => setName(e.target.value)}
          onBlur={() => r.is_published && onPublish(r, true, name)} />
      </td>
      <td>
        <label style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 12.5 }}>
          <input type="checkbox" checked={r.is_published} disabled={!canEdit || !r.feedback}
            onChange={(e) => onPublish(r, e.target.checked, name)} />
          {r.is_published ? 'Đang hiển thị' : 'Ẩn'}
        </label>
      </td>
    </tr>
  );
}
